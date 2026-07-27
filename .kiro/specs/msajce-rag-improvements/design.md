# Design Document: MSAJCE RAG Pipeline Improvements

## 1. Architecture Overview

### 1.1 Component Diagram (ASCII)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CLIENT (React + TypeScript)                         │
│  useCampusChat.ts  ──►  POST /api/chat  ◄──  FeedbackButtons component      │
│                         POST /api/feedback                                  │
│                         POST /api/chat/stream  (Req 10b)                    │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ HTTP
┌────────────────────────────────▼────────────────────────────────────────────┐
│                     api_server.py  (FastAPI)                                │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                     REQUEST PIPELINE                                 │   │
│  │                                                                      │   │
│  │  Step 0 ──► SpellCorrector ──────────────────────────────────────┐  │   │
│  │                (vocab.pkl lookup + Levenshtein ≤2)               │  │   │
│  │                                                                   ▼  │   │
│  │  Step 1 ──► IntentClassifier + KeywordExpander (LLM)             │  │   │
│  │                (+ category inference with confidence)            │  │   │
│  │                                                                   ▼  │   │
│  │  Step 2 ──► CacheLookup (Supabase SHA-256)                       │  │   │
│  │                bypass_cache flag honours Req 5.7                 │  │   │
│  │                                                                   ▼  │   │
│  │  Step 3 ──► QueryRewriter (condense-question, LLM)               │  │   │
│  │                only when session_id + ≥2 prior assistant turns   │  │   │
│  │                                                                   ▼  │   │
│  │  Step 4 ──► HybridRetriever ─────────────────────────────────┐   │  │   │
│  │             ├─ BM25IndexManager (rank_bm25, bm25.pkl)        │   │  │   │
│  │             ├─ DenseRetriever (Qdrant + MetadataFilter)      │   │  │   │
│  │             └─ RRF Fusion (k=60) → 40 candidates            │   │  │   │
│  │                                                              ▼   │  │   │
│  │  Step 5 ──► NvidiaReranker (Nemotron-Rerank-1b-v2) → top 6  │   │  │   │
│  │                DEBUG log logit scores                        │   │  │   │
│  │                                                              ▼   │  │   │
│  │  Step 6 ──► FaithfulnessChecker (conditional, LLM)          │   │  │   │
│  │                only when max_logit < FAITHFULNESS_TRIGGER    │   │  │   │
│  │                                                              ▼   │  │   │
│  │  Step 7 ──► LLMGenerator (Llama-3.1-8b)                     │   │  │   │
│  │                                                              ▼   │  │   │
│  │  Step 8 ──► CacheSave + ResponseBuild                        │   │  │   │
│  └──────────────────────────────────────────────────────────────┘   │   │
│                                                                             │
│  DEBUG:  GET  /api/debug/rerank                                             │
│          POST /api/feedback                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
         │                    │                      │
    ┌────▼─────┐      ┌───────▼──────┐      ┌───────▼──────┐
    │  Qdrant  │      │  Supabase    │      │  NVIDIA NIM  │
    │  Cloud   │      │  PostgreSQL  │      │  Endpoints   │
    │          │      │              │      │              │
    │collection│      │ chat_msgs    │      │ embed-1b     │
    │college_  │      │ chat_sessions│      │ llama-3.1-8b │
    │knowledge │      │ query_cache  │      │ nemotron-    │
    │base      │      │ msg_feedback │      │ rerank-1b    │
    └──────────┘      └──────────────┘      └──────────────┘
         │
    ┌────▼────────────────────────────────────┐
    │  bm25_index/  (local filesystem)        │
    │    bm25.pkl   (BM25Okapi index)          │
    │    vocab.pkl  (token→freq dict)          │
    └─────────────────────────────────────────┘
```

### 1.2 Request Data Flow (Happy Path)

```
User message  "admmision fees for cse"
      │
      ▼
[SpellCorrector]
  "admmision" → "admission"  (edit dist=1, freq≥5 in vocab.pkl)
  corrected: "admission fees for cse"
      │
      ▼
[IntentClassifier + KeywordExpander]
  intent:   "college_query"
  keywords: "CSE admission fees tuition charges B.E Computer Science"
  category: "Admission & Fees"  confidence: 0.87
      │
      ▼
[CacheLookup]  SHA-256("admission fees for cse") → miss
      │
      ▼
[QueryRewriter]  session_id present + 2 prior turns?
  NO → pass original query
      │
      ▼
[HybridRetriever]
  BM25: top-25 by BM25 score  (from bm25.pkl)
  Dense: top-25 cosine (Qdrant, filter: category="Admission & Fees")
  RRF fusion → 40 deduped candidates (Σ 1/(60+rank))
      │
      ▼
[NvidiaReranker] 40 passages → sorted by logit → top 6
  logits: [0.91, 0.87, 0.72, 0.55, 0.44, 0.38]
  max_logit = 0.91  → above FAITHFULNESS_TRIGGER_THRESHOLD(0.30)
      │
      ▼
[FaithfulnessChecker] SKIPPED (max_logit ≥ 0.30)
  trace: faithfulness_check_invoked=false, faithfulness_passed=null
      │
      ▼
[LLMGenerator] Llama-3.1-8b → answer text
      │
      ▼
[CacheSave]  INSERT query_cache ON CONFLICT DO NOTHING
      │
      ▼
ChatResponse { answer, citations, modelUsed, isCached, tokenUsage }
```

---

## 2. File Structure Changes

### 2.1 New Files

```
bm25_index/
  bm25.pkl           # Serialised BM25Okapi instance (rank_bm25 library)
  vocab.pkl          # dict[str, int] token → corpus frequency

eval/
  eval_dataset.json  # 30-50 Q&A ground-truth pairs
  run_eval.py        # CLI eval harness (Recall@6, EM, F1)
  results_*.json     # Auto-generated per-run output (gitignored)

pipeline/            # New package — extracted from api_server.py
  __init__.py
  spell_corrector.py
  query_rewriter.py
  hybrid_retriever.py
  bm25_index_manager.py
  metadata_filter.py
  faithfulness_checker.py
  chunker.py         # Replaces chunking logic in process_dataset.py

src/components/chat/
  FeedbackButtons.tsx  # New thumbs-up/down component
```

### 2.2 Modified Files

```
api_server.py          # Import pipeline/* modules, add new routes
process_dataset.py     # Replace chunk_section/split_into_sections with
                       #   pipeline/chunker.py, add BM25 rebuild call,
                       #   add --incremental CLI flag
rag_config.py          # All new constants (see Section 6)
schema.sql             # message_feedback table, chat_messages.metadata column
src/types/chat.ts      # Add feedbackState to ChatMessage interface
src/hooks/useCampusChat.ts  # Add session_id, feedback call, streaming mode
src/components/chat/MessageBubble.tsx  # Import FeedbackButtons
```

---

## 3. Component Designs

### 3.1 SpellCorrector (`pipeline/spell_corrector.py`)

**Purpose:** Correct misspelled tokens in raw user input before any LLM call.  
**Requirement:** Req 7

#### Class Signature

```python
import pickle, re, time
from pathlib import Path
from Levenshtein import distance as levenshtein_distance

VOCAB_PATH = Path("bm25_index/vocab.pkl")

class SpellCorrector:
    """
    Token-level spell corrector backed by a vocabulary built from all
    chunk text tokens in the Qdrant corpus plus static MSAJCE proper nouns.

    vocab: dict[str, int]  token → corpus frequency (case-folded, len≥4)
    """

    STATIC_VOCAB: list[str] = [
        # Departments
        "msajce", "admission", "placement", "hostel", "transport",
        "incubation", "iqac", "nirf", "alumni",
        # Department acronyms (short — exempt from len≥4 filter via static list)
        "cse", "ece", "eee", "csbs", "aiml", "aids", "cyber",
        # Degree codes
        "btech", "mtech", "mba", "barch",
    ]

    def __init__(self, vocab: dict[str, int] | None = None):
        if vocab is not None:
            self._vocab = vocab
        elif VOCAB_PATH.exists():
            with open(VOCAB_PATH, "rb") as f:
                self._vocab = pickle.load(f)
        else:
            self._vocab = {}
        # Merge static list with freq=999 so they always pass min_freq check
        for word in self.STATIC_VOCAB:
            self._vocab.setdefault(word, 999)

    @classmethod
    def build_from_texts(cls, texts: list[str]) -> "SpellCorrector":
        """Build vocab from a list of chunk text strings. Called by BM25IndexManager."""
        from collections import Counter
        TOKEN_RE = re.compile(r"[a-zA-Z]{4,}")  # len≥4, alpha only
        counts: Counter = Counter()
        for text in texts:
            tokens = TOKEN_RE.findall(text.lower())
            counts.update(tokens)
        vocab = dict(counts)
        Path("bm25_index").mkdir(exist_ok=True)
        with open(VOCAB_PATH, "wb") as f:
            pickle.dump(vocab, f)
        return cls(vocab)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _is_skip_token(token: str) -> bool:
        """Return True for tokens that must never be corrected."""
        if re.fullmatch(r"\d+", token):           # purely numeric
            return True
        if re.match(r"https?://|www\.", token):   # URL fragment
            return True
        return False

    def _best_candidate(self, token: str) -> str | None:
        """
        Return the closest vocabulary word within edit distance ≤2
        with corpus frequency ≥5, or None if no suitable candidate.
        """
        t = token.lower()
        if t in self._vocab:
            return None  # already correct
        best_word: str | None = None
        best_dist = 3  # sentinel > max allowed
        for word, freq in self._vocab.items():
            if freq < 5:
                continue
            if abs(len(word) - len(t)) > 2:
                continue  # fast length pre-filter
            d = levenshtein_distance(t, word)
            if d <= 2 and d < best_dist:
                best_dist = d
                best_word = word
        return best_word

    # ── Public API ────────────────────────────────────────────────────────────

    def correct(self, query: str) -> tuple[str, list[tuple[str, str]]]:
        """
        Correct query tokens in-place.

        Returns:
            corrected_query: str
            corrections: list[(original_token, corrected_token)]
        """
        t0 = time.monotonic()
        tokens = query.split()
        corrections: list[tuple[str, str]] = []
        result_tokens: list[str] = []

        for tok in tokens:
            if self._is_skip_token(tok):
                result_tokens.append(tok)
                continue
            candidate = self._best_candidate(tok)
            if candidate and candidate != tok.lower():
                corrections.append((tok, candidate))
                result_tokens.append(candidate)
            else:
                result_tokens.append(tok)

        elapsed_ms = (time.monotonic() - t0) * 1000
        # Performance guard: must finish under 50ms for ≤50 tokens (Req 7.8)
        if elapsed_ms > 50:
            import logging
            logging.warning(f"[SpellCorrector] took {elapsed_ms:.1f}ms for {len(tokens)} tokens")

        return " ".join(result_tokens), corrections
```

---

### 3.2 SemanticChunker (`pipeline/chunker.py`)

**Purpose:** Replace the ad-hoc chunking in `process_dataset.py` with a robust, requirement-compliant chunker.  
**Requirement:** Req 1

#### Key Design Decisions

- Chunk target: 400–900 chars (soft 600). Hard min: 60 chars non-whitespace.
- Overlap: 60–100 chars from last sentence of preceding chunk, same section only.
- Table detection: ≥3 consecutive lines each with ≥2 tab/multi-space columns.
- Table over 1 800 chars: split between complete rows, repeat header row.
- Deterministic chunk ID: `chunk_hash = SHA-256(text)[:16]`, point_id = `int(hash[:8], 16)`.

```python
import hashlib, re, logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

CHUNK_MIN   = 60
CHUNK_MAX   = 900
CHUNK_SOFT  = 600
OVERLAP_MIN = 60
OVERLAP_MAX = 100
TABLE_MAX_SINGLE = 1800

SECTION_HEADER_RE = re.compile(
    r"^(?:\d+[\.\)]\s+)?[A-Z][A-Za-z\s&/,—–\-]{3,80}(?::|—|–)?\s*$"
)
SENTENCE_END_RE = re.compile(r"(?<=[.?!])\s+")


@dataclass
class Chunk:
    text: str
    section_title: str
    source_file: str
    category: str
    page_number: int
    parent_id: str
    chunk_hash: str = field(init=False)
    point_id: int   = field(init=False)

    def __post_init__(self):
        h = hashlib.sha256(self.text.encode()).hexdigest()
        self.chunk_hash = h[:16]
        self.point_id   = int(h[:8], 16)


class SemanticChunker:
    """
    Semantic boundary-aware chunker (Requirement 1).
    Splits at paragraph, section, or table-row boundaries — never mid-sentence.
    """

    # ── Table detection ───────────────────────────────────────────────────────

    @staticmethod
    def _detect_table_block(lines: list[str]) -> list[tuple[int, int]]:
        """
        Return list of (start_idx, end_idx) ranges that are table blocks.
        A table block: ≥3 consecutive lines each with ≥2 tab- or 2+space-aligned columns.
        """
        def is_table_line(l: str) -> bool:
            return l.count("\t") >= 1 or (l.count("  ") >= 2 and bool(re.search(r"\S\s{2,}\S", l)))

        blocks = []
        i = 0
        while i < len(lines):
            if is_table_line(lines[i]):
                j = i
                while j < len(lines) and (is_table_line(lines[j]) or not lines[j].strip()):
                    j += 1
                if j - i >= 3:
                    blocks.append((i, j))
                    i = j
                    continue
            i += 1
        return blocks

    # ── Overlap extraction ────────────────────────────────────────────────────

    @staticmethod
    def _extract_overlap(text: str) -> str:
        """Return last 60–100 chars of `text` ending at a sentence boundary."""
        target = min(OVERLAP_MAX, max(OVERLAP_MIN, len(text) // 5))
        suffix = text[-target * 2:]       # grab extra to find a sentence break
        sentences = SENTENCE_END_RE.split(suffix)
        overlap = sentences[-1] if sentences else suffix
        return overlap[:OVERLAP_MAX]

    # ── Long paragraph splitter ───────────────────────────────────────────────

    @staticmethod
    def _split_long_para(para: str) -> list[str]:
        """
        Split a paragraph > CHUNK_MAX at nearest sentence end keeping
        both parts ≥ 200 chars (Req 1.4).
        """
        parts = SENTENCE_END_RE.split(para)
        segments: list[str] = []
        current = ""
        for sent in parts:
            if current and len(current) + len(sent) + 1 > CHUNK_MAX:
                if len(current) >= 200 and len(para) - len(current) >= 200:
                    segments.append(current.strip())
                    current = sent
                else:
                    current += " " + sent
            else:
                current = (current + " " + sent).strip() if current else sent
        if current:
            segments.append(current.strip())
        return segments if len(segments) > 1 else [para]

    # ── Table chunking ────────────────────────────────────────────────────────

    def _chunk_table(
        self, lines: list[str], title: str,
        meta: dict
    ) -> list["Chunk"]:
        """Keep table whole if ≤ TABLE_MAX_SINGLE, else split by rows with header."""
        header_prefix = f"## {title}\n\n" if title != "Overview" else ""
        full_text = header_prefix + "\n".join(lines)

        if len(full_text) <= TABLE_MAX_SINGLE:
            return [Chunk(text=full_text.strip(), section_title=title, **meta)]

        # Split between complete rows, repeat header row
        header_row = lines[0]
        chunks: list[Chunk] = []
        current_lines = [header_prefix + header_row]
        for row in lines[1:]:
            candidate = "\n".join(current_lines + [row])
            if len(candidate) > TABLE_MAX_SINGLE and len(current_lines) > 1:
                block = "\n".join(current_lines).strip()
                if len(block) >= CHUNK_MIN:
                    chunks.append(Chunk(text=block, section_title=title, **meta))
                current_lines = [header_prefix + header_row, row]
            else:
                current_lines.append(row)
        if current_lines:
            block = "\n".join(current_lines).strip()
            if len(block) >= CHUNK_MIN:
                chunks.append(Chunk(text=block, section_title=title, **meta))
        return chunks

    # ── Section-level chunking ────────────────────────────────────────────────

    def chunk_section(self, title: str, body: str, meta: dict) -> list["Chunk"]:
        """
        Chunk a single section body into Chunk objects.
        `meta` contains: source_file, category, page_number, parent_id
        """
        lines = body.splitlines()
        table_ranges = self._detect_table_block(lines)
        table_range_set = set()
        for s, e in table_ranges:
            table_range_set.update(range(s, e))

        chunks: list[Chunk] = []
        # Separate non-table paragraphs from table blocks in order
        segments: list[dict] = []  # {"type": "para"|"table", "content": str|list[str]}

        para_lines: list[str] = []
        i = 0
        while i < len(lines):
            # Check if this line starts a table block
            in_table = next(((s, e) for s, e in table_ranges if s == i), None)
            if in_table is not None:
                if para_lines:
                    segments.append({"type": "para", "content": "\n".join(para_lines)})
                    para_lines = []
                segments.append({"type": "table", "content": lines[in_table[0]:in_table[1]]})
                i = in_table[1]
            else:
                para_lines.append(lines[i])
                i += 1
        if para_lines:
            segments.append({"type": "para", "content": "\n".join(para_lines)})

        overlap_text = ""
        header_prefix = f"## {title}\n\n" if title != "Overview" else ""

        for seg in segments:
            if seg["type"] == "table":
                chunks.extend(self._chunk_table(seg["content"], title, meta))
                overlap_text = ""  # No overlap across table boundaries
                continue

            # Paragraph chunking
            paragraphs = re.split(r"\n{2,}", seg["content"])
            current = header_prefix + (overlap_text + "\n\n" if overlap_text else "")

            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                # Long paragraph: split at sentence boundary first
                sub_paras = self._split_long_para(para) if len(para) > CHUNK_MAX else [para]
                for sp in sub_paras:
                    if len(current) + len(sp) + 2 <= CHUNK_SOFT:
                        current += sp + "\n\n"
                    else:
                        if len(current.strip()) >= CHUNK_MIN:
                            overlap_text = self._extract_overlap(current.strip())
                            chunks.append(Chunk(text=current.strip(), section_title=title, **meta))
                        current = header_prefix + overlap_text + "\n\n" + sp + "\n\n"
                        overlap_text = ""

            # Flush
            remainder = current.strip()
            if len(remainder) >= CHUNK_MIN:
                overlap_text = self._extract_overlap(remainder)
                chunks.append(Chunk(text=remainder, section_title=title, **meta))
            elif chunks:
                # Merge short remainder into last chunk (Req 1.8)
                prev = chunks[-1]
                merged = prev.text + "\n\n" + remainder
                chunks[-1] = Chunk(text=merged, section_title=title, **meta)

        return chunks

    # ── Full document chunking ────────────────────────────────────────────────

    def chunk_document(
        self,
        text: str,
        source_file: str,
        category: str,
        page_number: int,
        parent_id: str,
    ) -> list["Chunk"]:
        """Top-level entry: split text into sections, then chunk each."""
        from pipeline.chunker import split_into_sections  # local import
        meta = dict(source_file=source_file, category=category,
                    page_number=page_number, parent_id=parent_id)
        sections = split_into_sections(text)
        all_chunks: list[Chunk] = []
        for sec in sections:
            all_chunks.extend(self.chunk_section(sec["title"], sec["body"], meta))

        # Stats log (Req 1.7)
        lengths = [len(c.text) for c in all_chunks]
        if lengths:
            logger.info(
                f"[Chunker] {source_file}: {len(all_chunks)} chunks | "
                f"min={min(lengths)} max={max(lengths)} mean={sum(lengths)//len(lengths)}"
            )
        return all_chunks


def split_into_sections(text: str) -> list[dict]:
    """Identical to existing logic in process_dataset.py — canonical location."""
    lines = text.splitlines()
    sections, current_title, current_lines = [], "Overview", []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            current_lines.append("")
            continue
        if SECTION_HEADER_RE.match(stripped) and len(stripped) < 100:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append({"title": current_title, "body": body})
            current_title = stripped.rstrip(":—–-").strip()
            current_lines = []
        else:
            current_lines.append(line)
    body = "\n".join(current_lines).strip()
    if body:
        sections.append({"title": current_title, "body": body})
    return sections or [{"title": "Overview", "body": text}]
```

---

### 3.3 BM25IndexManager (`pipeline/bm25_index_manager.py`)

**Purpose:** Build, persist, load, and serve the BM25 keyword index.  
**Requirement:** Req 3, Req 7

```python
import pickle, logging, time
from pathlib import Path
from rank_bm25 import BM25Okapi
from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

BM25_PATH      = Path("bm25_index/bm25.pkl")
META_PATH      = Path("bm25_index/bm25_meta.pkl")  # {"point_count": int, "built_at": float}
COLLECTION_NAME = "college_knowledgebase"


class BM25IndexManager:
    """
    Manages a rank_bm25.BM25Okapi index over all chunk texts.

    Persistence layout:
      bm25_index/bm25.pkl      — pickled BM25Okapi instance
      bm25_index/bm25_meta.pkl — {"point_count": int, "texts": list[str],
                                   "payloads": list[dict], "built_at": float}
      bm25_index/vocab.pkl     — dict[str, int] rebuilt alongside BM25

    Staleness detection: compare stored point_count vs qdrant.count().
    """

    def __init__(self, qdrant: QdrantClient):
        self._qdrant = qdrant
        self._bm25:  BM25Okapi | None = None
        self._texts: list[str]        = []
        self._payloads: list[dict]    = []

    # ── Startup ───────────────────────────────────────────────────────────────

    def load_or_build(self) -> None:
        """
        Called once at API server startup.
        - If pkl absent or corrupted → rebuild from Qdrant.
        - If point count stale → rebuild.
        - Else → load from pkl.
        """
        live_count = self._qdrant.count(COLLECTION_NAME).count

        if BM25_PATH.exists() and META_PATH.exists():
            try:
                with open(META_PATH, "rb") as f:
                    meta = pickle.load(f)
                stored_count = meta.get("point_count", -1)
                if stored_count == live_count:
                    with open(BM25_PATH, "rb") as f:
                        self._bm25 = pickle.load(f)
                    self._texts    = meta["texts"]
                    self._payloads = meta["payloads"]
                    logger.info(f"[BM25] Loaded from cache ({live_count} points).")
                    return
                else:
                    logger.info(
                        f"[BM25] Stale index (stored={stored_count}, live={live_count}). Rebuilding."
                    )
            except Exception as e:
                logger.warning(f"[BM25] Failed to load pkl: {e}. Rebuilding.")
        else:
            logger.info("[BM25] Index not found. Building from Qdrant.")

        self._rebuild(live_count)

    def _rebuild(self, point_count: int) -> None:
        """Scroll all Qdrant points, build BM25Okapi, persist."""
        texts, payloads = [], []
        offset = None
        while True:
            batch, next_offset = self._qdrant.scroll(
                collection_name=COLLECTION_NAME,
                limit=500,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for pt in batch:
                text = pt.payload.get("text", "")
                if text:
                    texts.append(text)
                    payloads.append(pt.payload)
            if next_offset is None:
                break
            offset = next_offset

        tokenized = [t.lower().split() for t in texts]
        bm25 = BM25Okapi(tokenized)

        Path("bm25_index").mkdir(exist_ok=True)
        with open(BM25_PATH, "wb") as f:
            pickle.dump(bm25, f)
        meta = {"point_count": point_count, "texts": texts,
                "payloads": payloads, "built_at": time.time()}
        with open(META_PATH, "wb") as f:
            pickle.dump(meta, f)

        self._bm25 = bm25
        self._texts = texts
        self._payloads = payloads

        # Rebuild vocab.pkl alongside (Req 7.6)
        from pipeline.spell_corrector import SpellCorrector
        SpellCorrector.build_from_texts(texts)
        logger.info(f"[BM25] Rebuilt index: {len(texts)} chunks, vocab refreshed.")

    # ── Query ─────────────────────────────────────────────────────────────────

    def query(self, query: str, top_k: int = 25) -> list[dict]:
        """
        Return up to top_k results as list of {"text": str, "payload": dict, "bm25_rank": int}.
        Raises RuntimeError if index not loaded (caller must handle for graceful degradation).
        """
        if self._bm25 is None:
            raise RuntimeError("BM25 index not loaded.")
        tokenized_query = query.lower().split()
        scores = self._bm25.get_scores(tokenized_query)
        # Get indices sorted by descending score
        ranked_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        results = []
        for rank, idx in enumerate(ranked_idx):
            if scores[idx] > 0:  # non-zero BM25 score required (Req 3.6)
                results.append({
                    "text":     self._texts[idx],
                    "payload":  self._payloads[idx],
                    "bm25_rank": rank,
                    "bm25_score": float(scores[idx]),
                })
        return results

    # ── Incremental append (Req 3.7) ─────────────────────────────────────────

    def append_and_rebuild(self, new_texts: list[str], new_payloads: list[dict]) -> None:
        """Called by process_dataset.py after indexing a new PDF."""
        self._texts.extend(new_texts)
        self._payloads.extend(new_payloads)
        live_count = self._qdrant.count(COLLECTION_NAME).count
        self._rebuild(live_count)
```

---

### 3.4 HybridRetriever (`pipeline/hybrid_retriever.py`)

**Purpose:** Merge BM25 and dense results via RRF, pass 40 candidates to reranker.  
**Requirement:** Req 3

```python
import logging, concurrent.futures
from pipeline.bm25_index_manager import BM25IndexManager
from pipeline.metadata_filter import MetadataFilter
from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

RRF_K   = 60    # RRF constant
TOP_K   = 25    # per-retriever candidate count
RRF_OUT = 40    # merged candidates to reranker


class HybridRetriever:
    """
    Parallel BM25 + dense search merged via Reciprocal Rank Fusion.

    score(d) = Σ 1 / (RRF_K + rank(d))
    """

    def __init__(
        self,
        bm25_mgr: BM25IndexManager,
        qdrant: QdrantClient,
        embed_fn,           # callable(str) -> list[float]
        collection: str,
    ):
        self._bm25    = bm25_mgr
        self._qdrant  = qdrant
        self._embed   = embed_fn
        self._coll    = collection
        self._filter  = MetadataFilter()

    def retrieve(
        self,
        query: str,
        keywords: str,
        category: str | None = None,
    ) -> list[dict]:
        """
        Returns up to RRF_OUT (40) deduplicated candidate dicts:
          {"text": str, "payload": dict, "rrf_score": float}

        Falls back to dense-only if BM25 raises (Req 3.9).
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            dense_future = ex.submit(self._dense_search, keywords, category)
            bm25_future  = ex.submit(self._bm25_search, keywords)

            dense_results = dense_future.result()
            try:
                bm25_results = bm25_future.result()
            except Exception as e:
                logger.warning(f"[HybridRetriever] BM25 failed, using dense-only: {e}")
                bm25_results = []

        return self._rrf_fuse(bm25_results, dense_results)

    # ── BM25 search ───────────────────────────────────────────────────────────

    def _bm25_search(self, query: str) -> list[dict]:
        return self._bm25.query(query, top_k=TOP_K)

    # ── Dense search ──────────────────────────────────────────────────────────

    def _dense_search(self, keywords: str, category: str | None) -> list[dict]:
        vec = self._embed(keywords)
        qdrant_filter = self._filter.build_filter(category) if category else None
        hits = []

        if qdrant_filter:
            try:
                raw = self._qdrant.query_points(
                    collection_name=self._coll,
                    query=vec,
                    query_filter=qdrant_filter,
                    limit=TOP_K,
                    with_payload=True,
                )
                hits = raw.points
                if len(hits) < 10:
                    logger.warning(
                        f"[MetadataFilter] category='{category}' returned {len(hits)} hits — "
                        f"falling back to unfiltered search."
                    )
                    hits = []  # trigger fallback
            except Exception:
                hits = []

        if not hits:
            raw = self._qdrant.query_points(
                collection_name=self._coll,
                query=vec,
                limit=TOP_K,
                with_payload=True,
            )
            hits = raw.points

        return [
            {"text": h.payload.get("text", ""), "payload": h.payload,
             "dense_score": h.score, "dense_rank": rank}
            for rank, h in enumerate(hits)
        ]

    # ── RRF Fusion ────────────────────────────────────────────────────────────

    def _rrf_fuse(
        self,
        bm25_results: list[dict],
        dense_results: list[dict],
    ) -> list[dict]:
        """
        Merge two ranked lists via RRF.
        score(d) = Σ 1 / (RRF_K + rank(d))
        Deduplication key: first 100 chars of normalised text.
        """
        scores: dict[str, float] = {}
        best:   dict[str, dict]  = {}

        def _key(d: dict) -> str:
            return d["text"][:100].lower().strip()

        for rank, item in enumerate(bm25_results):
            k = _key(item)
            scores[k] = scores.get(k, 0.0) + 1.0 / (RRF_K + rank)
            best[k] = item

        for rank, item in enumerate(dense_results):
            k = _key(item)
            scores[k] = scores.get(k, 0.0) + 1.0 / (RRF_K + rank)
            if k not in best:
                best[k] = item

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:RRF_OUT]
        return [
            {**best[k], "rrf_score": score}
            for k, score in ranked
        ]
```

---

### 3.5 MetadataFilter (`pipeline/metadata_filter.py`)

**Purpose:** Build Qdrant payload filters from inferred category.  
**Requirement:** Req 2

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue

class MetadataFilter:
    """
    Wraps Qdrant filter construction for category-based payload filtering.
    The CATEGORY_LIST in rag_config.py is the canonical source of valid values.
    """

    def build_filter(self, category: str) -> Filter:
        """Return a Qdrant Filter restricting `category` field to exact match."""
        return Filter(
            must=[
                FieldCondition(
                    key="category",
                    match=MatchValue(value=category),
                )
            ]
        )
```

Category inference is added to `preprocess_query()` in `api_server.py` by extending the LLM system prompt to also return `"category"` and `"category_confidence"` fields in the JSON response. The pipeline only applies the filter when `category_confidence >= CATEGORY_CONFIDENCE_THRESHOLD` (default 0.70, defined in `rag_config.py`).

**Extended preprocess_query JSON contract:**

```json
{
  "intent": "college_query",
  "keywords": "CSE admission fees B.E computer science",
  "direct_response": "",
  "category": "Admission & Fees",
  "category_confidence": 0.87
}
```

---

### 3.6 QueryRewriter (`pipeline/query_rewriter.py`)

**Purpose:** Condense multi-turn follow-up into a self-contained question.  
**Requirement:** Req 6

```python
import json, logging, requests
from typing import Optional

logger = logging.getLogger(__name__)

CONDENSE_SYSTEM = """You are a query rewriter for a college chatbot.
Given a conversation history and a new user message, rewrite the user message
into a single self-contained question that can be answered without any prior context.

Rules:
- If the message is already self-contained, return it UNCHANGED.
- Output ONLY the rewritten question, no explanation, no JSON, no quotes.
- Do not invent information not present in the conversation.
"""


class QueryRewriter:
    """
    Rewrites follow-up questions into standalone queries (condense-question pattern).
    Only invoked when session_id has ≥2 prior assistant turns.
    """

    def __init__(self, nvidia_api_key: str, model: str = "meta/llama-3.1-8b-instruct"):
        self._key   = nvidia_api_key
        self._model = model

    def rewrite(
        self,
        current_message: str,
        history: list[dict],   # [{"role": "user"|"assistant", "content": str}, ...]
    ) -> str:
        """
        Returns rewritten standalone question, or original message on failure.
        `history` should contain the last 4 turns (8 messages max).
        """
        if not history:
            return current_message

        # Build conversation context string
        ctx_lines = []
        for turn in history[-8:]:  # last 4 pairs
            role = turn["role"].capitalize()
            ctx_lines.append(f"{role}: {turn['content']}")
        context_str = "\n".join(ctx_lines)

        user_prompt = f"Conversation so far:\n{context_str}\n\nNew message: {current_message}"

        try:
            res = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._key}",
                         "Content-Type": "application/json"},
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": CONDENSE_SYSTEM},
                        {"role": "user",   "content": user_prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 120,
                },
                timeout=10,
            )
            res.raise_for_status()
            rewritten = res.json()["choices"][0]["message"]["content"].strip()
            logger.debug(f"[QueryRewriter] '{current_message}' → '{rewritten}'")
            return rewritten or current_message
        except Exception as e:
            logger.warning(f"[QueryRewriter] Failed: {e}. Using original message.")
            return current_message


def fetch_session_history(conn, session_id: str, limit: int = 8) -> list[dict]:
    """
    Fetch the last `limit` turns from chat_messages for a session.
    Returns list of {"role": str, "content": str}.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT role, content FROM chat_messages
        WHERE session_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (session_id, limit),
    )
    rows = cur.fetchall()
    cur.close()
    # Reverse so oldest first
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def should_rewrite(history: list[dict]) -> bool:
    """Return True when there are ≥2 prior assistant turns in history (Req 6.1)."""
    assistant_turns = sum(1 for h in history if h["role"] == "assistant")
    return assistant_turns >= 2
```

---

### 3.7 FaithfulnessChecker (`pipeline/faithfulness_checker.py`)

**Purpose:** Optional LLM grounding verification on low-confidence retrievals.  
**Requirement:** Req 8

```python
import logging, requests

logger = logging.getLogger(__name__)

FALLBACK_ANSWER = (
    "I don't have reliable information on that. "
    "Please contact the MSAJCE office at +91 99400 04500 or msajce.office@gmail.com."
)

FAITHFULNESS_PROMPT = """You are a faithfulness checker for a college Q&A system.

Given an AI-generated answer and the source context, determine whether every
factual claim in the answer is directly supported by the context.

Respond with ONLY one word: YES or NO.
Do not explain. Do not add anything else.

Context:
{context}

Answer to verify:
{answer}
"""


class FaithfulnessChecker:
    """
    Conditional faithfulness check (Requirement 8).
    Only invoked when max_rerank_logit < FAITHFULNESS_TRIGGER_THRESHOLD.
    """

    def __init__(self, nvidia_api_key: str, model: str = "meta/llama-3.1-8b-instruct"):
        self._key   = nvidia_api_key
        self._model = model

    def check(
        self,
        answer: str,
        context_blocks: list[dict],
        timeout: float = 10.0,
    ) -> tuple[bool, bool | None]:
        """
        Returns (check_invoked=True, faithfulness_passed: bool|None).
        faithfulness_passed=None means the LLM call failed (Req 8.7).
        """
        context_str = "\n\n---\n\n".join(b["text"] for b in context_blocks)
        prompt = FAITHFULNESS_PROMPT.format(context=context_str, answer=answer)

        try:
            res = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._key}",
                         "Content-Type": "application/json"},
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 5,
                },
                timeout=timeout,
            )
            res.raise_for_status()
            verdict = res.json()["choices"][0]["message"]["content"].strip().upper()
            passed = verdict.startswith("YES")
            logger.debug(f"[FaithfulnessChecker] verdict={verdict} → passed={passed}")
            return True, passed
        except Exception as e:
            logger.warning(f"[FaithfulnessChecker] LLM call failed: {e}. Returning None.")
            return True, None  # invoked=True, passed=None per Req 8.7
```

**Integration in `chat_endpoint`:**

```python
# After rerank, before LLM generation:
max_logit = max((r.get("logit", 0.0) for r in rankings), default=0.0)

answer, g_usage = generate_answer(user_query, context_blocks)

faithfulness_check_invoked = False
faithfulness_passed        = None

if max_logit < FAITHFULNESS_TRIGGER_THRESHOLD:
    faithfulness_check_invoked = True
    _, faithfulness_passed = faithfulness_checker.check(answer, context_blocks)
    if faithfulness_passed is False:
        answer = FALLBACK_ANSWER

trace["faithfulness_check_invoked"] = faithfulness_check_invoked
trace["faithfulness_passed"]        = faithfulness_passed
```

---

### 3.8 FeedbackEndpoint

**Purpose:** Record thumbs-up/down signals per assistant message.  
**Requirement:** Req 9

The endpoint is added directly to `api_server.py`.

```python
class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str
    rating: int          # Must be -1 or 1

class FeedbackResponse(BaseModel):
    status: str


@app.post("/api/feedback", response_model=FeedbackResponse)
def feedback_endpoint(req: FeedbackRequest):
    # Validate rating before any DB call (Req 9.4)
    if req.rating not in (-1, 1):
        raise HTTPException(422, detail={"error": "rating must be -1 or 1"})

    try:
        conn = db_connect()
        conn.autocommit = True
        cur  = conn.cursor()

        # Verify message_id exists (Req 9.3)
        cur.execute("SELECT id FROM chat_messages WHERE id = %s", (req.message_id,))
        if cur.fetchone() is None:
            cur.close(); conn.close()
            raise HTTPException(404, detail={"error": "message not found"})

        # Upsert — ON CONFLICT allows rating change (Req 9.7)
        cur.execute(
            """
            INSERT INTO message_feedback (message_id, session_id, rating)
            VALUES (%s, %s, %s)
            ON CONFLICT (message_id) DO UPDATE
              SET rating     = EXCLUDED.rating,
                  created_at = CURRENT_TIMESTAMP
            """,
            (req.message_id, req.session_id, req.rating),
        )
        cur.close(); conn.close()
        return FeedbackResponse(status="ok")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
```

---

### 3.9 EvalHarness (`eval/run_eval.py`)

**Purpose:** Offline metrics to measure pipeline quality with each change.  
**Requirement:** Req 5

#### Dataset Schema (`eval/eval_dataset.json`)

```json
[
  {
    "id": "q001",
    "question": "What are the tuition fees for B.E. CSE at MSAJCE?",
    "expected_answer": "The tuition fee for B.E. Computer Science and Engineering is Rs. 65,000 per year.",
    "category": "Admission & Fees",
    "source_file": "msajce_admission.pdf",
    "expected_chunk_ids": ["optional — SHA-256 prefix of expected chunk text"]
  }
]
```

Minimum 30 entries, ≥8 category values, ≥5 exact-identifier questions (bus routes, staff names, course codes).

#### Metrics Implementation

```python
#!/usr/bin/env python3
"""
Usage:
  python eval/run_eval.py
  python eval/run_eval.py --bypass-cache --pipeline-variant hybrid
"""

import argparse, json, time, re, math
from datetime import datetime
from pathlib import Path
import requests

API_BASE = "http://localhost:8000"

# ── Token F1 helper ───────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b\w+\b", text.lower())

def token_f1(prediction: str, ground_truth: str) -> float:
    pred_tokens = _tokenize(prediction)
    gt_tokens   = _tokenize(ground_truth)
    if not pred_tokens or not gt_tokens:
        return 0.0
    pred_set = set(pred_tokens)
    gt_set   = set(gt_tokens)
    common   = pred_set & gt_set
    if not common:
        return 0.0
    precision = len(common) / len(pred_set)
    recall    = len(common) / len(gt_set)
    return 2 * precision * recall / (precision + recall)

def exact_match(prediction: str, ground_truth: str) -> bool:
    return prediction.strip().lower() == ground_truth.strip().lower()

def recall_at_k(citations: list[dict], source_file: str) -> bool:
    """Check whether expected source_file appears in top-k citations."""
    return any(c.get("source", "").lower() == source_file.lower() for c in citations)


# ── Main eval loop ────────────────────────────────────────────────────────────

def run(args):
    dataset_path = Path(__file__).parent / "eval_dataset.json"
    with open(dataset_path) as f:
        dataset = json.load(f)

    results = []
    for item in dataset:
        payload = {
            "message":      item["question"],
            "bypass_cache": args.bypass_cache,
        }
        t0 = time.monotonic()
        try:
            resp = requests.post(f"{API_BASE}/api/chat", json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [ERROR] {item['id']}: {e}")
            results.append({"id": item["id"], "error": str(e)})
            continue
        latency = time.monotonic() - t0

        answer    = data.get("answer", "")
        citations = data.get("citations", [])

        r6   = recall_at_k(citations, item["source_file"])
        em   = exact_match(answer, item["expected_answer"])
        f1   = token_f1(answer, item["expected_answer"])

        entry = {
            "id":          item["id"],
            "question":    item["question"],
            "category":    item["category"],
            "recall_at_6": r6,
            "exact_match": em,
            "f1":          round(f1, 4),
            "latency_s":   round(latency, 2),
            "pipeline_variant": args.pipeline_variant,
        }
        results.append(entry)

        status = "✓" if r6 else "✗"
        print(f"  [{status}] {item['id']} | R@6={int(r6)} EM={int(em)} F1={f1:.2f} ({latency:.1f}s)")

    # Aggregate
    valid   = [r for r in results if "error" not in r]
    avg_r6  = sum(r["recall_at_6"] for r in valid) / len(valid) if valid else 0
    avg_em  = sum(r["exact_match"]  for r in valid) / len(valid) if valid else 0
    avg_f1  = sum(r["f1"]           for r in valid) / len(valid) if valid else 0

    print(f"\n{'='*50}")
    print(f"  Recall@6:    {avg_r6:.3f}")
    print(f"  Exact-Match: {avg_em:.3f}")
    print(f"  Token F1:    {avg_f1:.3f}")
    print(f"{'='*50}\n")

    out = {
        "run_at":  datetime.utcnow().isoformat(),
        "variant": args.pipeline_variant,
        "summary": {"recall_at_6": avg_r6, "exact_match": avg_em, "f1": avg_f1},
        "questions": results,
    }
    out_path = Path(__file__).parent / f"results_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Results written to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bypass-cache",     action="store_true")
    parser.add_argument("--pipeline-variant", default="default")
    run(parser.parse_args())
```

---

## 4. Database Schema Changes

### 4.1 New Table: `message_feedback`

```sql
-- Req 9.1
CREATE TABLE IF NOT EXISTS message_feedback (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL UNIQUE REFERENCES chat_messages(id) ON DELETE CASCADE,
    session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
    rating     SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Req 9.8
CREATE INDEX IF NOT EXISTS idx_message_feedback_message
    ON message_feedback(message_id);

CREATE INDEX IF NOT EXISTS idx_message_feedback_session
    ON message_feedback(session_id);
```

### 4.2 Modified Table: `chat_messages`

Add `metadata` JSONB column to store `rewritten_query` and per-request trace (Req 6.5):

```sql
ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

-- Index for session history lookups in QueryRewriter
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_role
    ON chat_messages(session_id, role, created_at);
```

**Example metadata content for an assistant message:**

```json
{
  "rewritten_query":           "What are the annual tuition fees for CSE?",
  "rerank_used":               true,
  "faithfulness_check_invoked": false,
  "faithfulness_passed":       null,
  "category_inferred":        "Admission & Fees",
  "category_confidence":       0.87,
  "spell_corrections":        [["admmision", "admission"]],
  "max_rerank_logit":          0.91
}
```

### 4.3 Modified Table: `chat_messages` — message_id in response

The `POST /api/chat` response must return the persisted `message_id` so the frontend can submit feedback. This requires persisting the assistant message to `chat_messages` before responding, and including `message_id` in `ChatResponse`.

```sql
-- Ensure chat_messages insert happens in chat_endpoint before response is returned.
-- No schema change required, but chat_endpoint must INSERT the assistant message
-- and return its id.
```

---

## 5. API Contract Changes

### 5.1 Modified: `POST /api/chat`

**Request** (extended):

```json
{
  "message":      "What are the fees for CSE?",
  "session_id":   "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "bypass_cache": false
}
```

**Response** (extended):

```json
{
  "answer":     "The annual tuition fee for B.E. CSE is Rs. 65,000...",
  "citations":  [
    { "source": "msajce_admission.pdf", "page": "3", "section": "Fee Structure" }
  ],
  "modelUsed":  "meta/llama-3.1-8b-instruct",
  "isCached":   false,
  "tokenUsage": { "prompt_tokens": 812, "completion_tokens": 94, "total_tokens": 906 },
  "message_id": "a1b2c3d4-0000-0000-0000-000000000001",
  "trace": {
    "intent":                     "college_query",
    "category_inferred":          "Admission & Fees",
    "category_confidence":        0.87,
    "rewritten_query":            null,
    "rerank_used":                true,
    "max_rerank_logit":           0.91,
    "faithfulness_check_invoked": false,
    "faithfulness_passed":        null,
    "spell_corrections":          []
  }
}
```

**Pydantic models (additions):**

```python
class TraceInfo(BaseModel):
    intent:                     str
    category_inferred:          Optional[str]   = None
    category_confidence:        Optional[float] = None
    rewritten_query:            Optional[str]   = None
    rerank_used:                bool            = True
    max_rerank_logit:           Optional[float] = None
    faithfulness_check_invoked: bool            = False
    faithfulness_passed:        Optional[bool]  = None
    spell_corrections:          list            = []

class ChatResponse(BaseModel):
    answer:     str
    citations:  List[Citation]
    modelUsed:  str
    isCached:   bool
    tokenUsage: Optional[TokenUsage] = None
    message_id: Optional[str]        = None   # UUID of persisted assistant message
    trace:      Optional[TraceInfo]  = None
```

---

### 5.2 New: `POST /api/feedback`

**Request:**

```json
{ "message_id": "a1b2c3d4-...", "session_id": "3fa85f64-...", "rating": 1 }
```

**Responses:**

| Status | Body |
|--------|------|
| 200 | `{"status": "ok"}` |
| 404 | `{"error": "message not found"}` |
| 422 | `{"error": "rating must be -1 or 1"}` |
| 500 | `{"error": "<exception message>"}` |

---

### 5.3 New: `GET /api/debug/rerank`

**Request:**

```json
{
  "query":    "Who is the principal of MSAJCE?",
  "passages": ["Dr. M. Srinivasan is the Principal...", "The CSE department offers..."]
}
```

**Response:**

```json
{
  "query": "Who is the principal of MSAJCE?",
  "rankings": [
    { "index": 0, "logit": 0.92, "passage_preview": "Dr. M. Srinivasan is the Principal..." },
    { "index": 1, "logit": 0.04, "passage_preview": "The CSE department offers..." }
  ],
  "threshold": 0.01,
  "raw_response": { ... }
}
```

---

### 5.4 New: `POST /api/chat/stream` (Req 10b)

**Request:** Same as `/api/chat`.

**Response:** `text/event-stream` (SSE)

```
data: {"token": "The "}

data: {"token": "tuition "}

data: {"token": "fee... "}

event: done
data: {"citations": [...], "tokenUsage": {...}, "message_id": "..."}
```

---

## 6. `rag_config.py` Additions

```python
# rag_config.py  — additions for MSAJCE RAG Improvements

# ── Chunking (Req 1) ──────────────────────────────────────────────────────────
CHUNK_MIN_CHARS     = 60    # discard/merge chunks shorter than this
CHUNK_MAX_CHARS     = 900   # hard upper bound; split at sentence end
CHUNK_SOFT_TARGET   = 600   # preferred chunk size
OVERLAP_MIN_CHARS   = 60    # overlap range lower bound
OVERLAP_MAX_CHARS   = 100   # overlap range upper bound
TABLE_MAX_SINGLE    = 1800  # max chars to keep a table in one chunk

# ── Category list (Req 2) ─────────────────────────────────────────────────────
# Canonical set of payload `category` values used in Qdrant.
# Add new categories here when new PDFs introduce them; no code change needed.
CATEGORY_LIST: list[str] = [
    "Department — Computer Science & Engineering",
    "Department — CS & Business Systems",
    "Department — CS & Cyber Security",
    "Department — AI & Data Science",
    "Department — AI & Machine Learning",
    "Department — Information Technology",
    "Department — Electronics & Communication",
    "Department — Electrical & Electronics",
    "Department — Science & Humanities",
    "Alumni Association",
    "Placement & Careers",
    "Admission & Fees",
    "Hostel & Accommodation",
    "Transport & Bus Routes",
    "Research & Publications",
    "Incubation Centre",
    "Technology Centre",
    "Library",
    "IQAC & Accreditation",
    "NIRF Ranking",
    "Sports & Athletics",
    "Clubs & Societies",
    "Professional Societies",
    "About MSAJCE",
    "General — MSAJCE",
]

# Minimum LLM confidence to apply metadata filter (Req 2.2)
CATEGORY_CONFIDENCE_THRESHOLD = 0.70

# ── Hybrid search / BM25 (Req 3) ─────────────────────────────────────────────
BM25_INDEX_DIR  = "bm25_index"      # directory containing bm25.pkl and vocab.pkl
RRF_K           = 60                # RRF rank constant
HYBRID_TOP_K    = 25                # candidates per retriever leg
RRF_MERGE_SIZE  = 40                # merged candidates sent to reranker

# ── Re-ranker (Req 4) ─────────────────────────────────────────────────────────
RERANK_SCORE_THRESHOLD = 0.01       # chunks below this logit are filtered out
RERANK_TOP_N           = 6          # final chunks after re-ranking

# ── Query rewriting (Req 6) ───────────────────────────────────────────────────
QUERY_REWRITE_MIN_TURNS = 2         # min prior assistant turns to trigger rewrite
QUERY_REWRITE_HISTORY   = 4         # number of prior turn pairs to include

# ── Spell correction (Req 7) ──────────────────────────────────────────────────
SPELL_VOCAB_PATH        = "bm25_index/vocab.pkl"
SPELL_MAX_EDIT_DISTANCE = 2
SPELL_MIN_TOKEN_FREQ    = 5
SPELL_MIN_TOKEN_LEN     = 4

# ── Faithfulness checker (Req 8) ─────────────────────────────────────────────
FAITHFULNESS_TRIGGER_THRESHOLD = 0.30   # max rerank logit below which check is invoked
FAITHFULNESS_LLM_TIMEOUT       = 10.0   # seconds

# ── Feedback (Req 9) ──────────────────────────────────────────────────────────
# (No extra config needed beyond schema; included here for completeness)
FEEDBACK_TABLE = "message_feedback"
```

---

## 7. Frontend Changes

### 7.1 `src/types/chat.ts` — Extended Interface

```typescript
export interface Citation {
  source:   string;
  page?:    number | string;
  section?: string;
  category?: string;
  url?:     string;
}

export interface TokenUsage {
  prompt_tokens:     number;
  completion_tokens: number;
  total_tokens:      number;
}

export type FeedbackState = "idle" | "submitting" | "submitted";

export interface ChatMessage {
  id:          string;
  role:        "user" | "assistant" | "system";
  content:     string;
  createdAt:   number;
  citations?:  Citation[];
  modelUsed?:  string;
  isCached?:   boolean;
  tokenUsage?: TokenUsage;
  // New fields (Req 9)
  messageId?:    string;          // persisted DB id for feedback
  feedbackState?: FeedbackState;  // "idle" | "submitting" | "submitted"
  feedbackRating?: 1 | -1 | null; // recorded rating
  // Animation state
  isAnimating?:  boolean;
}
```

---

### 7.2 `src/components/chat/FeedbackButtons.tsx` (New File)

```tsx
import { useState } from "react";
import { ThumbsUp, ThumbsDown, Check } from "lucide-react";
import { cn } from "@/lib/utils";

interface FeedbackButtonsProps {
  messageId:  string;
  sessionId?: string;
  onFeedback?: (rating: 1 | -1) => void;
}

const API_BASE = "http://localhost:8000";

export function FeedbackButtons({
  messageId,
  sessionId,
  onFeedback,
}: FeedbackButtonsProps) {
  const [state,  setState]  = useState<"idle" | "submitting" | "done">("idle");
  const [rating, setRating] = useState<1 | -1 | null>(null);

  const submit = async (r: 1 | -1) => {
    if (state !== "idle") return;
    setState("submitting");
    try {
      await fetch(`${API_BASE}/api/feedback`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          message_id: messageId,
          session_id: sessionId ?? "",
          rating:     r,
        }),
      });
      setRating(r);
      setState("done");
      onFeedback?.(r);
    } catch {
      setState("idle");  // allow retry on network error
    }
  };

  if (state === "done") {
    return (
      <div
        className="mt-1 flex items-center gap-1 text-[11px]"
        style={{ color: "var(--muted-foreground)" }}
      >
        <Check className="size-3" style={{ color: "oklch(0.65 0.17 145)" }} />
        <span>Feedback recorded</span>
      </div>
    );
  }

  const disabled = state === "submitting";

  return (
    <div className="mt-1 flex items-center gap-1">
      <button
        disabled={disabled}
        aria-label="Thumbs up"
        onClick={() => submit(1)}
        className={cn(
          "p-1 rounded transition-colors",
          disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer hover:bg-black/5"
        )}
        style={{ color: "var(--muted-foreground)" }}
      >
        <ThumbsUp className="size-3.5" />
      </button>
      <button
        disabled={disabled}
        aria-label="Thumbs down"
        onClick={() => submit(-1)}
        className={cn(
          "p-1 rounded transition-colors",
          disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer hover:bg-black/5"
        )}
        style={{ color: "var(--muted-foreground)" }}
      >
        <ThumbsDown className="size-3.5" />
      </button>
    </div>
  );
}
```

---

### 7.3 `src/components/chat/MessageBubble.tsx` — Changes

Add `FeedbackButtons` below the token-usage footer, rendered only when the message is fully rendered (no blinking cursor, `tokenUsage` is present):

```tsx
// At the bottom of the assistant message bubble, after token usage block:
{!isUser && message.tokenUsage && message.messageId && (
  <FeedbackButtons
    messageId={message.messageId}
    sessionId={/* pass from useCampusChat context */}
  />
)}
```

The `isAnimating` check ensures buttons never show until the message is complete (Req 9.4). A message is considered fully rendered when `message.tokenUsage !== undefined` — the existing pattern in `MessageBubble.tsx`.

---

### 7.4 `src/hooks/useCampusChat.ts` — Changes

```typescript
// Key additions only; full file preserved with these changes:

// 1. Add session_id state
const [sessionId, setSessionId] = useState<string | null>(null);

// 2. Pass session_id in POST body
body: JSON.stringify({ message: text, session_id: sessionId }),

// 3. Capture message_id from response
const aiMessage: ChatMessage = {
  ...
  messageId: data.message_id ?? undefined,  // for FeedbackButtons
};

// 4. Initialise or reuse session_id from response
// (session_id could be generated client-side with crypto.randomUUID())
// Generate once per hook mount:
const sessionIdRef = useRef<string>(crypto.randomUUID());

// Pass in every request body:
body: JSON.stringify({ message: text, session_id: sessionIdRef.current }),

// 5. SSE streaming support (Req 10b) — opt-in via config
interface UseCampusChatOptions {
  onAnimationDone?: (userMsgId: string) => void;
  streaming?: boolean;
}

// When streaming=true, connect to /api/chat/stream and update message content
// incrementally; show FeedbackButtons only after "event: done" is received.
```

---

## 8. Request Trace Object

Every request through `chat_endpoint` accumulates a `trace` dict that is:
1. Logged at DEBUG level.
2. Returned in the `ChatResponse.trace` field (for dev builds; could be stripped in prod).
3. Stored as `chat_messages.metadata` JSONB for the assistant message.

```python
# Initialised at start of chat_endpoint:
trace: dict = {
    # Input processing
    "original_query":            user_query,
    "spell_corrections":         [],          # list[(original, corrected)]
    "corrected_query":           user_query,  # after SpellCorrector
    "intent":                    "",
    "keywords":                  "",
    "category_inferred":         None,        # str | None
    "category_confidence":       None,        # float | None

    # Cache
    "cache_hit":                 False,
    "bypass_cache":              req.bypass_cache,

    # Query rewriting
    "session_history_turns":     0,
    "rewrite_triggered":         False,
    "rewritten_query":           None,        # str | None

    # Retrieval
    "bm25_candidate_count":      0,
    "dense_candidate_count":     0,
    "rrf_merged_count":          0,
    "metadata_filter_applied":   False,
    "metadata_filter_fallback":  False,

    # Reranking
    "rerank_used":               True,
    "rerank_logits":             [],          # list[float] — all logits, DEBUG only
    "max_rerank_logit":          None,        # float | None
    "rerank_fallback":           False,       # True if all logits < threshold

    # Faithfulness
    "faithfulness_check_invoked": False,
    "faithfulness_passed":        None,       # bool | None

    # Output
    "answer_replaced_by_fallback": False,
}
```

The trace is populated incrementally through each pipeline step and serialised to JSON for storage. Fields `rerank_logits` (full array) is excluded from the stored JSONB but included in DEBUG log output.

---

## 9. Implementation Order

Dependencies drive the build order. Each phase can begin once its dependency is unblocked.

### Phase 1 — Foundation (no blocking dependencies)

| Priority | Item | File(s) |
|----------|------|---------|
| 1.1 | `rag_config.py` additions | `rag_config.py` |
| 1.2 | `pipeline/` package skeleton (`__init__.py`) | `pipeline/__init__.py` |
| 1.3 | `SemanticChunker` + `split_into_sections` | `pipeline/chunker.py` |
| 1.4 | Update `process_dataset.py` to use `SemanticChunker` | `process_dataset.py` |
| 1.5 | `schema.sql` migrations (message_feedback, chat_messages.metadata) | `schema.sql` |

**Rationale:** Chunking quality (Req 1) is the foundation for all retrieval quality. Database schema must be in place before any new endpoint writes to it.

---

### Phase 2 — Index & Vocabulary

| Priority | Item | File(s) |
|----------|------|---------|
| 2.1 | `BM25IndexManager` | `pipeline/bm25_index_manager.py` |
| 2.2 | `SpellCorrector` + `vocab.pkl` build | `pipeline/spell_corrector.py` |
| 2.3 | Integrate BM25 rebuild into `process_dataset.py` | `process_dataset.py` |
| 2.4 | Add `--incremental` CLI flag to `process_dataset.py` | `process_dataset.py` |

**Rationale:** BM25 and vocab require the chunker output to be complete first. `SpellCorrector` depends on `vocab.pkl`, which is built alongside the BM25 index.

---

### Phase 3 — API Server Pipeline Components

Build and integrate into `api_server.py` in pipeline order:

| Priority | Item | File(s) |
|----------|------|---------|
| 3.1 | `SpellCorrector` integration (Step 0) | `api_server.py` |
| 3.2 | `MetadataFilter` + extended `preprocess_query` (category + confidence) | `pipeline/metadata_filter.py`, `api_server.py` |
| 3.3 | `HybridRetriever` (parallel BM25 + dense + RRF) | `pipeline/hybrid_retriever.py`, `api_server.py` |
| 3.4 | DEBUG logging for rerank logits + `/api/debug/rerank` endpoint | `api_server.py` |
| 3.5 | `QueryRewriter` + session history fetch | `pipeline/query_rewriter.py`, `api_server.py` |
| 3.6 | `FaithfulnessChecker` (conditional) | `pipeline/faithfulness_checker.py`, `api_server.py` |
| 3.7 | Trace dict assembly + `ChatResponse` extensions (`message_id`, `trace`) | `api_server.py` |
| 3.8 | `POST /api/feedback` endpoint | `api_server.py` |
| 3.9 | `bypass_cache` flag in `ChatRequest` | `api_server.py` |

---

### Phase 4 — Evaluation

| Priority | Item | File(s) |
|----------|------|---------|
| 4.1 | `eval/eval_dataset.json` (30–50 Q&A pairs) | `eval/eval_dataset.json` |
| 4.2 | `eval/run_eval.py` (Recall@6, EM, F1, CLI flags) | `eval/run_eval.py` |
| 4.3 | Baseline run (pre-improvements) | — |
| 4.4 | Post-improvement comparison run | — |

---

### Phase 5 — Frontend

| Priority | Item | File(s) |
|----------|------|---------|
| 5.1 | `src/types/chat.ts` extensions | `src/types/chat.ts` |
| 5.2 | `FeedbackButtons` component | `src/components/chat/FeedbackButtons.tsx` |
| 5.3 | `MessageBubble.tsx` — integrate `FeedbackButtons` | `src/components/chat/MessageBubble.tsx` |
| 5.4 | `useCampusChat.ts` — `sessionId`, `message_id` capture | `src/hooks/useCampusChat.ts` |

---

### Phase 6 — Lower-Priority (Req 10)

| Priority | Item | File(s) |
|----------|------|---------|
| 6.1 | Query decomposition (`compound_query` intent, max 3 sub-questions) | `api_server.py` |
| 6.2 | `POST /api/chat/stream` SSE endpoint | `api_server.py` |
| 6.3 | `useCampusChat.ts` streaming mode | `src/hooks/useCampusChat.ts` |

---

## 10. Key Design Decisions & Rationale

### 10.1 `pipeline/` Package vs Monolithic `api_server.py`

Extracting each pipeline component into `pipeline/` makes unit testing possible (each class can be tested in isolation) and decouples the HTTP layer from business logic. `api_server.py` becomes a thin orchestrator.

### 10.2 BM25 Persistence Strategy

Using `rank_bm25.BM25Okapi` with pickle serialisation is the simplest approach for a single-node deployment. The staleness check (point count comparison) avoids rebuild on every restart while still catching re-index events. For multi-node deployments, the pkl files would need to move to shared storage or be replaced with a Redis-backed index — out of scope for this spec.

### 10.3 chunk_hash vs MD5 → SHA-256

The current code uses `MD5` for `chunk_hash` (fast, 32 hex chars). Req 1.9 requires preservation of all payload fields including `chunk_hash`. The new `SemanticChunker` switches to SHA-256 for collision resistance and uses the first 16 hex chars as the stored hash. The `point_id` derivation (`int(hash[:8], 16)`) is preserved for Qdrant upsert compatibility.

### 10.4 Faithfulness Checker — Null State

`faithfulness_passed: null` represents two distinct cases: (a) check was not invoked (high-confidence path) and (b) check was invoked but the LLM call failed. Both cases should not suppress the generated answer. The `faithfulness_check_invoked` boolean disambiguates them in the trace.

### 10.5 Feedback Upsert

`ON CONFLICT (message_id) DO UPDATE` allows users to change their rating (e.g., thumbs-up to thumbs-down). The frontend disables buttons after submission but a second POST from a refreshed session can still update the stored rating. This is intentional and preferred over a hard-reject on duplicate submissions.

### 10.6 Session ID Generation

`sessionId` is generated client-side using `crypto.randomUUID()` once per hook mount. It is not persisted in `localStorage` intentionally — each page load starts a fresh session. This keeps session history well-bounded and avoids stale context contamination across visits.
