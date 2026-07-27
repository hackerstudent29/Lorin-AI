# Implementation Tasks

## Overview

This document breaks down the MSAJCE RAG improvement specification into individual implementation tasks, organized by dependency phase. Each task references specific requirements and design sections, includes file paths, and provides clear acceptance criteria.

**Total estimated effort:** 16-20 developer days across 6 phases

**Dependency phases** (from design.md Section 9):
- **Phase 1:** Foundation (config, chunker, schema) — 3 days
- **Phase 2:** BM25 + Spell Correction — 2.5 days
- **Phase 3:** Full Pipeline Integration — 4 days
- **Phase 4:** Evaluation Harness — 1.5 days
- **Phase 5:** Frontend Feedback UI — 2 days
- **Phase 6:** Lower Priority Features — 3 days (optional)

---

## Phase 1: Foundation (3 days)

### Task 1.1: Create `rag_config.py` Constants File

**Requirements:** All (cross-cutting configuration)  
**Design:** Section 6  
**Priority:** P0 — blocking all other work  
**Estimate:** 2 hours

#### Description
Extract all hardcoded magic numbers from `api_server.py` and `process_dataset.py` into a single `rag_config.py` constants file. This centralizes tuning parameters and makes all thresholds discoverable.

#### Files to Create
- `rag_config.py`

#### Files to Modify
- `api_server.py` (replace literals with imports)
- `process_dataset.py` (replace literals)

#### Acceptance Criteria
1. `rag_config.py` exports all constants listed in Design Section 6:
   - `CHUNK_MIN`, `CHUNK_MAX`, `CHUNK_SOFT`, `OVERLAP_MIN`, `OVERLAP_MAX`, `TABLE_MAX_SINGLE`
   - `CATEGORY_LIST` (list of all known category strings from Qdrant)
   - `CATEGORY_CONFIDENCE_THRESHOLD = 0.70`
   - `BM25_TOP_K = 25`, `DENSE_TOP_K = 25`, `RRF_K = 60`, `RRF_OUTPUT_SIZE = 40`
   - `RERANK_TOP_N = 6`, `RERANK_SCORE_THRESHOLD = 0.01`
   - `REWRITE_MIN_HISTORY_TURNS = 2`, `REWRITE_MAX_CONTEXT_TURNS = 4`

---

### Task 1.2: Create Database Schema Migrations

**Status:** `backlog`  
**Requirements:** Req 8.6, Req 9.1–9.8  
**Design Reference:** Design.md Section 4

**Description:**  
Add `message_feedback` table and extend `chat_messages` with `metadata JSONB` column for storing internal trace data.

**Acceptance Criteria:**
- [ ] `schema.sql` updated with new DDL:
  ```sql
  -- Add metadata column to existing table
  ALTER TABLE chat_messages 
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

  -- Create feedback table
  CREATE TABLE IF NOT EXISTS message_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL UNIQUE REFERENCES chat_messages(id) ON DELETE CASCADE,
    session_id UUID,
    rating SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
  );

  CREATE INDEX IF NOT EXISTS idx_message_feedback_message_id 
    ON message_feedback(message_id);
  CREATE INDEX IF NOT EXISTS idx_message_feedback_created_at 
    ON message_feedback(created_at DESC);
  ```
- [ ] Migration script runs without errors on existing Supabase database
- [ ] `message_id` column has `NOT NULL UNIQUE` constraint (fixes Bug #1 from requirements)
- [ ] No data loss in existing `chat_messages` rows
- [ ] Verify `ON CONFLICT (message_id)` works in feedback upsert query

**Files Modified:**
- `schema.sql`

**Verification:**
```bash
# Connect to Supabase and verify
psql $DATABASE_URL -c "\d message_feedback"
psql $DATABASE_URL -c "\d chat_messages" | grep metadata
```

   - `SPELL_MIN_FREQ = 5`, `SPELL_MAX_EDIT_DIST = 2`, `SPELL_TIMEOUT_MS = 50`
   - `FAITHFULNESS_TRIGGER_THRESHOLD = 0.30`, `FAITHFULNESS_TIMEOUT_SEC = 10`
   - `FEEDBACK_VALID_RATINGS = [-1, 1]`
2. All imports of these constants work correctly in `api_server.py` and `process_dataset.py`
3. Server starts without errors after replacing literals

#### Testing
- Start API server → no import errors
- Run `python process_dataset.py --help` → no import errors
- Run existing integration test suite (if any) → all pass

---

### Task 1.2: Implement `SemanticChunker` Class

**Requirements:** Req 1 (all 10 criteria)  
**Design:** Section 3.2  
**Priority:** P0 — blocking all indexing work  
**Estimate:** 8 hours

#### Description
Replace the ad-hoc chunking logic in `process_dataset.py` with a robust, requirement-compliant `SemanticChunker` class that respects semantic boundaries (paragraphs, sections, table rows) and never splits mid-sentence.

#### Files to Create
- `pipeline/__init__.py` (empty)
- `pipeline/chunker.py` (contains `SemanticChunker` and `split_into_sections()`)

---

### Task 1.3: Extract `SemanticChunker` into `pipeline/chunker.py`

**Status:** `backlog`  
**Requirements:** Req 1.1–1.10  
**Design Reference:** Design.md Section 3.2

**Description:**  
Replace ad-hoc chunking logic in `process_dataset.py` with a semantic boundary-aware chunker class that respects paragraph, section, and table boundaries.

**Acceptance Criteria:**
- [ ] Create directory `pipeline/` with `__init__.py`
- [ ] Create `pipeline/chunker.py` containing:
  - `SemanticChunker` class with methods:
    - `_detect_table_block(lines)` — regex detection for ≥3 lines with ≥2 tab/space-aligned columns
    - `_extract_overlap(text)` — return 60–100 char suffix ending at sentence boundary
    - `_split_long_para(para)` — split paragraphs >900 chars at sentence boundaries (both parts ≥200 chars)
    - `_chunk_table(lines, title, meta)` — keep table whole if ≤1800 chars, else split between rows with repeated header
    - `chunk_section(title, body, meta)` — main entry per section
    - `chunk_document(text, source_file, category, page_number, parent_id)` — full doc entry
  - `Chunk` dataclass with fields: `text`, `section_title`, `source_file`, `category`, `page_number`, `parent_id`, `chunk_hash` (SHA-256 first 16 hex chars), `point_id` (int from first 8 hex chars)
  - `split_into_sections(text)` function moved from `process_dataset.py`
- [ ] Chunker produces chunks between 400–900 chars (soft target 600), hard minimum 60 non-whitespace chars
- [ ] Overlap: 60–100 chars from last sentence of previous chunk, same section only
- [ ] Tables detected and kept whole unless >1800 chars
- [ ] No mid-sentence splits (split only at `.?!` followed by whitespace)
- [ ] Each chunk gets `section_title` from enclosing section heading or `"Overview"`
- [ ] All existing payload fields preserved: `source_file`, `category`, `section_title`, `page_number`, `parent_id`, `chunk_hash`

**Files Created:**
- `pipeline/__init__.py`
- `pipeline/chunker.py`

**Verification:**
```python
from pipeline.chunker import SemanticChunker, Chunk
chunker = SemanticChunker()
test_text = "Section 1: Test\n\nParagraph one. " + ("More text. " * 50)
chunks = chunker.chunk_document(test_text, "test.pdf", "Test", 1, "test_parent")
assert all(60 <= len(c.text) <= 900 for c in chunks)
assert all(c.section_title != "" for c in chunks)
print(f"✓ Generated {len(chunks)} valid chunks")
```


---

### Task 1.4: Update `process_dataset.py` to Use `SemanticChunker`

**Status:** `backlog`  
**Requirements:** Req 1.7, Req 1.9, Req 1.10  
**Design Reference:** Design.md Section 3.2

**Description:**  
Replace inline chunking logic with calls to `SemanticChunker`, add per-PDF stats logging, ensure deterministic `chunk_hash` IDs for safe upserts.

**Acceptance Criteria:**
- [ ] Import `from pipeline.chunker import SemanticChunker, Chunk`
- [ ] Remove old `chunk_section()` and `split_into_sections()` functions (now in `pipeline/chunker.py`)
- [ ] Instantiate `chunker = SemanticChunker()` at module level
- [ ] Replace chunking call with:
  ```python
  chunks = chunker.chunk_document(
      text=cleaned_text,
      source_file=pdf_path.name,
      category=category,
      page_number=page_num,
      parent_id=parent_id
  )
  ```
- [ ] Log per-PDF stats after chunking completes:
  ```python
  lengths = [len(c.text) for c in chunks]
  logger.info(f"[Chunker] {pdf_path.name}: {len(chunks)} chunks | "
              f"min={min(lengths)} max={max(lengths)} mean={sum(lengths)//len(lengths)}")
  ```
- [ ] Use `chunk.point_id` as Qdrant point ID (ensures deterministic IDs for safe re-indexing)
- [ ] Verify no short chunks (<60 chars) are upserted to Qdrant
- [ ] All existing metadata fields preserved in upsert

**Files Modified:**
- `process_dataset.py`

**Verification:**
```bash
python process_dataset.py --pdf dataset/msajce_about.pdf
# Check logs for stats: "X chunks | min=Y max=Z mean=W"
# Verify no "chunk too short" errors
```

---

## Phase 2: BM25 Index and Spell Correction

### Task 2.1: Implement `BM25IndexManager`

**Status:** `backlog`  
**Requirements:** Req 3.2, Req 3.3, Req 3.7, Req 3.8  
**Design Reference:** Design.md Section 3.3

**Description:**  
Create a manager class that builds, persists, loads, and queries a BM25 keyword index over all chunk texts in Qdrant.

**Acceptance Criteria:**
- [ ] Create `pipeline/bm25_index_manager.py` with `BM25IndexManager` class
- [ ] Install dependency: `pip install rank-bm25` (add to `requirements.txt`)
- [ ] Class methods:
  - `__init__(qdrant_client)` — store client reference
  - `load_or_build()` — called at API startup, loads from pkl or rebuilds if stale/missing
  - `_rebuild(point_count)` — scroll all Qdrant points (limit=500), build `BM25Okapi`, persist to `bm25_index/bm25.pkl` and `bm25_index/bm25_meta.pkl`
  - `query(query, top_k=25)` — return list of `{"text": str, "payload": dict, "bm25_rank": int, "bm25_score": float}`
  - `append_and_rebuild(new_texts, new_payloads)` — called after new PDF indexed (Req 3.7)
- [ ] Persistence schema:
  - `bm25.pkl` — serialized `BM25Okapi` instance
  - `bm25_meta.pkl` — `{"point_count": int, "texts": list[str], "payloads": list[dict], "built_at": float}`
- [ ] Staleness detection: compare `meta["point_count"]` vs `qdrant.count().count`
- [ ] If pkl absent/corrupted at startup → rebuild from Qdrant, log event, continue without error (Req 3.8)
- [ ] Tokenization: lowercase `.split()` (consistent with BM25Okapi default)
- [ ] Only return results with `bm25_score > 0` (Req 3.6)

**Files Created:**
- `pipeline/bm25_index_manager.py`
- `bm25_index/` directory (created at runtime)

**Files Modified:**
- `requirements.txt` (add `rank-bm25`)

**Verification:**
```python
from pipeline.bm25_index_manager import BM25IndexManager
from qdrant_client import QdrantClient
qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
mgr = BM25IndexManager(qdrant)
mgr.load_or_build()
results = mgr.query("CSE department", top_k=10)
assert len(results) <= 10
assert all(r["bm25_score"] > 0 for r in results)
print(f"✓ BM25 returned {len(results)} results")
```


---

### Task 2.2: Implement `SpellCorrector`

**Status:** `backlog`  
**Requirements:** Req 7.1–7.8  
**Design Reference:** Design.md Section 3.1

**Description:**  
Create a vocabulary-based spell corrector using Levenshtein edit distance ≤2 against known MSAJCE terms and corpus tokens.

**Acceptance Criteria:**
- [ ] Create `pipeline/spell_corrector.py` with `SpellCorrector` class
- [ ] Install dependency: `pip install python-Levenshtein` (add to `requirements.txt`)
- [ ] Class structure:
  - `STATIC_VOCAB` — list of MSAJCE terms: department names, degree codes, course acronyms (CSE, ECE, EEE, CSBS, AIML, AIDS, CYBER, etc.)
  - `__init__(vocab=None)` — loads from `bm25_index/vocab.pkl` if exists, else empty dict; merges static vocab with freq=999
  - `build_from_texts(texts)` — class method, builds vocab from chunk texts (tokens len≥4, alpha only), saves to `vocab.pkl`
  - `_is_skip_token(token)` — return True for numeric tokens, URLs
  - `_best_candidate(token)` — find closest vocab word with edit distance ≤2, freq≥5, length pre-filter `abs(len(word)-len(token))≤2`
  - `correct(query)` — return `(corrected_query, corrections_list)`
- [ ] Tokenization: simple `.split()` on whitespace
- [ ] Performance: must complete in <50ms for ≤50 tokens (Req 7.8), log warning if exceeded
- [ ] Only correct tokens not already in vocab (exact match check first)
- [ ] Never modify: purely numeric tokens, URL fragments (`http://`, `www.`)
- [ ] Vocab file co-located with BM25 index (rebuilt together, Req 7.6)

**Files Created:**
- `pipeline/spell_corrector.py`
- `bm25_index/vocab.pkl` (created by `build_from_texts`)

**Files Modified:**
- `requirements.txt` (add `python-Levenshtein`)

**Verification:**
```python
from pipeline.spell_corrector import SpellCorrector
corrector = SpellCorrector.build_from_texts(["admission", "department", "computer science"])
corrected, changes = corrector.correct("admision departmnt")
assert corrected == "admission department", f"Got: {corrected}"
assert len(changes) == 2
print(f"✓ Corrected: {changes}")
```

---

### Task 2.3: Update `BM25IndexManager` to Rebuild Vocab Alongside BM25

**Status:** `backlog`  
**Requirements:** Req 7.6, Req 7.7  
**Design Reference:** Design.md Section 3.3 (rebuild method)

**Description:**  
Ensure that whenever the BM25 index is rebuilt, the spell corrector vocabulary is also rebuilt from the same corpus.

**Acceptance Criteria:**
- [ ] At end of `BM25IndexManager._rebuild()`, call:
  ```python
  from pipeline.spell_corrector import SpellCorrector
  SpellCorrector.build_from_texts(self._texts)
  logger.info(f"[BM25] Rebuilt index: {len(texts)} chunks, vocab refreshed.")
  ```
- [ ] Vocab build completes successfully as part of rebuild operation
- [ ] If vocab build fails, log error but don't block BM25 index rebuild (graceful degradation)
- [ ] Verify both `bm25.pkl` and `vocab.pkl` exist after rebuild

**Files Modified:**
- `pipeline/bm25_index_manager.py`

**Verification:**
```bash
# Delete both pkl files
rm bm25_index/bm25.pkl bm25_index/vocab.pkl bm25_index/bm25_meta.pkl
# Start server (triggers rebuild)
python api_server.py
# Verify both files exist
ls -lh bm25_index/
```

---

### Task 2.4: Add BM25 Rebuild Hook to `process_dataset.py`

**Status:** `backlog`  
**Requirements:** Req 3.7  
**Design Reference:** Design.md Section 3.3 (incremental append)

**Description:**  
After a new PDF is successfully indexed, notify the BM25 manager to rebuild the index with the new chunks.

**Acceptance Criteria:**
- [ ] At end of `process_dataset.py` main loop (after all PDFs processed), instantiate `BM25IndexManager` and call `append_and_rebuild()`
- [ ] Pass newly created chunk texts and payloads:
  ```python
  from pipeline.bm25_index_manager import BM25IndexManager
  bm25_mgr = BM25IndexManager(qdrant_client)
  bm25_mgr.append_and_rebuild(new_texts=[c.text for c in all_new_chunks],
                               new_payloads=[c.payload for c in all_new_chunks])
  ```
- [ ] Rebuild triggered only if at least one new PDF was indexed (skip if `--incremental` found no changes)
- [ ] Log message: `[BM25] Triggered rebuild after indexing X new PDFs`
- [ ] If BM25 rebuild fails, log error but don't fail the indexing job (chunks already in Qdrant)

**Files Modified:**
- `process_dataset.py`

**Verification:**
```bash
python process_dataset.py --pdf dataset/new_doc.pdf
# Check logs for "[BM25] Triggered rebuild"
# Verify bm25_meta.pkl updated timestamp
```

---

## Phase 3: Full API Pipeline Integration

### Task 3.1: Implement `MetadataFilter`

**Status:** `backlog`  
**Requirements:** Req 2.1–2.6  
**Design Reference:** Design.md Section 3.4 (partial), Section 2.1 Step 4

**Description:**  
Create a helper class that builds Qdrant payload filters for category-based retrieval with fallback logic.

**Acceptance Criteria:**
- [ ] Create `pipeline/metadata_filter.py` with `MetadataFilter` class
- [ ] Method `build_filter(category: str | None)` returns:
  - `None` if `category` is `None`
  - Qdrant `Filter` object matching `payload["category"] == category` otherwise
- [ ] Method `should_fallback(hit_count: int, category: str)` returns `True` if `hit_count < MIN_CATEGORY_HITS` (10)
- [ ] Import category list from `rag_config.py` for validation (Req 2.4)
- [ ] Log warning when fallback triggered: `[MetadataFilter] Category '{category}' returned only {hit_count} hits, falling back to unfiltered search`

**Files Created:**
- `pipeline/metadata_filter.py`

**Verification:**
```python
from pipeline.metadata_filter import MetadataFilter
from qdrant_client.models import Filter
mf = MetadataFilter()
f = mf.build_filter("Admission & Fees")
assert isinstance(f, Filter)
assert mf.should_fallback(8, "Rare Category") == True
assert mf.should_fallback(15, "Common Category") == False
print("✓ MetadataFilter working")
```


---

### Task 3.2: Implement `HybridRetriever` with RRF Fusion

**Status:** `backlog`  
**Requirements:** Req 3.1, Req 3.4, Req 3.5, Req 3.9  
**Design Reference:** Design.md Section 3.4

**Description:**  
Create a retriever that performs parallel BM25 + dense vector search, merges results via Reciprocal Rank Fusion, and returns up to 40 candidates for reranking.

**Acceptance Criteria:**
- [ ] Create `pipeline/hybrid_retriever.py` with `HybridRetriever` class
- [ ] Constructor: `__init__(bm25_mgr, qdrant_client, embed_fn, collection_name)`
- [ ] Method `retrieve(query, keywords, category=None)` returns list of up to 40 dicts:
  ```python
  {"text": str, "payload": dict, "rrf_score": float, "dense_rank": int, "bm25_rank": int}
  ```
- [ ] Implementation:
  - Use `concurrent.futures.ThreadPoolExecutor` to run BM25 and dense searches in parallel
  - BM25: query with `keywords`, get top 25
  - Dense: embed `query`, search Qdrant with optional `MetadataFilter`, get top 25
  - Deduplicate by `chunk_hash` (payload field)
  - Apply RRF: `score(d) = Σ 1/(60 + rank_in_list(d))` across both lists
  - Sort by RRF score descending, return top 40
- [ ] Graceful degradation (Req 3.9): if `bm25_mgr.query()` raises exception, log `WARN` and proceed with dense-only results
- [ ] Log at `DEBUG` level: number of BM25 candidates, dense candidates, deduplicated total, final RRF count

**Files Created:**
- `pipeline/hybrid_retriever.py`

**Verification:**
```python
from pipeline.hybrid_retriever import HybridRetriever
# ... setup bm25_mgr, qdrant, embed_fn ...
retriever = HybridRetriever(bm25_mgr, qdrant, embed_fn, "college_knowledgebase")
results = retriever.retrieve("admission fees", "admission tuition fees B.E", category=None)
assert len(results) <= 40
assert all("rrf_score" in r for r in results)
print(f"✓ HybridRetriever returned {len(results)} fused results")
```

---

### Task 3.3: Implement `QueryRewriter` for Multi-Turn Conversations

**Status:** `backlog`  
**Requirements:** Req 6.1–6.8  
**Design Reference:** Design.md Section 3.4 (QueryRewriter stub), Section 7 (chat_messages metadata)

**Description:**  
Create an LLM-based component that rewrites follow-up messages into standalone questions using conversation history (condense-question pattern).

**Acceptance Criteria:**
- [ ] Create `pipeline/query_rewriter.py` with `QueryRewriter` class
- [ ] Constructor: `__init__(llm_client, supabase_client)` — needs access to LLM and `chat_messages` table
- [ ] Method `rewrite(user_message, session_id)` returns `(rewritten_query: str, was_rewritten: bool)`
- [ ] Logic:
  - If `session_id` is `None` → return `(user_message, False)`
  - Query `chat_messages` for last 4 turns in session (2 user + 2 assistant), ordered by `created_at DESC`
  - If fewer than `MIN_SESSION_TURNS` (2) assistant turns exist → return `(user_message, False)`
  - Build condense-question prompt:
    ```
    You are rewriting a follow-up question into a standalone question using conversation history.
    
    History:
    User: {turn[-4]}
    Assistant: {turn[-3]}
    User: {turn[-2]}
    Assistant: {turn[-1]}
    
    Current question: {user_message}
    
    Rewrite the current question as a standalone, self-contained question. If it's already standalone, return it unchanged.
    Standalone question:
    ```
  - Call LLM (Llama-3.1-8b), extract rewritten query from response
  - If LLM call fails/times out → log `WARN`, return `(user_message, False)` (Req 6.6)
- [ ] Return `(rewritten, True)` if rewrite succeeded and differs from original
- [ ] Timeout: 10 seconds for LLM call

**Files Created:**
- `pipeline/query_rewriter.py`

**Verification:**
```python
from pipeline.query_rewriter import QueryRewriter
# Mock session with history in DB
rewriter = QueryRewriter(llm_client, supabase)
rewritten, changed = rewriter.rewrite("what about the fees?", session_id="test-session")
assert changed == True
assert "fees" in rewritten.lower()
print(f"✓ Rewritten: {rewritten}")
```

---

### Task 3.4: Implement `FaithfulnessChecker`

**Status:** `backlog`  
**Requirements:** Req 8.1–8.8  
**Design Reference:** Design.md Section 3.4 (partial)

**Description:**  
Create a conditional LLM component that verifies generated answers are grounded in retrieved context, invoked only when reranker confidence is low.

**Acceptance Criteria:**
- [ ] Create `pipeline/faithfulness_checker.py` with `FaithfulnessChecker` class
- [ ] Constructor: `__init__(llm_client)`
- [ ] Method `check(answer, context, max_rerank_logit)` returns `(should_replace: bool, was_invoked: bool, passed: bool | None)`
- [ ] Logic:
  - If `max_rerank_logit >= FAITHFULNESS_TRIGGER_THRESHOLD` (0.30) → return `(False, False, None)` immediately (Req 8.4, 8.8)
  - Build grounding prompt:
    ```
    Context:
    {context}
    
    Answer:
    {answer}
    
    Is every factual claim in the Answer supported by the Context? Answer only "yes" or "no".
    ```
  - Call LLM with 10-second timeout (Req 8.7)
  - Parse response: if contains "no" (case-insensitive) → return `(True, True, False)` (replace answer)
  - If contains "yes" → return `(False, True, True)` (answer is grounded)
  - If LLM fails/times out → log `WARN`, return `(False, True, None)` (don't replace, but mark invoked)
- [ ] Replacement text: `"I don't have reliable information on that. Please contact the MSAJCE office at +91 99400 04500 or msajce.office@gmail.com."` (Req 8.3)

**Files Created:**
- `pipeline/faithfulness_checker.py`

**Verification:**
```python
from pipeline.faithfulness_checker import FaithfulnessChecker
checker = FaithfulnessChecker(llm_client)
# High confidence → skip check
should_replace, invoked, passed = checker.check("CSE has 180 seats", "context...", max_rerank_logit=0.85)
assert invoked == False and passed is None

# Low confidence, grounded answer
should_replace, invoked, passed = checker.check("CSE has 180 seats", "CSE offers 180 seats", max_rerank_logit=0.25)
assert invoked == True and passed == True and should_replace == False
print("✓ FaithfulnessChecker working")
```


---

### Task 3.5: Integrate All Pipeline Components into `api_server.py`

**Status:** `backlog`  
**Requirements:** All Req 1–8 (full pipeline)  
**Design Reference:** Design.md Section 1.2 (request flow), Section 2.2

**Description:**  
Wire all new pipeline components into the `/api/chat` endpoint request flow, replacing existing retrieval logic.

**Acceptance Criteria:**
- [ ] Add imports at top of `api_server.py`:
  ```python
  from pipeline.spell_corrector import SpellCorrector
  from pipeline.query_rewriter import QueryRewriter
  from pipeline.bm25_index_manager import BM25IndexManager
  from pipeline.hybrid_retriever import HybridRetriever
  from pipeline.metadata_filter import MetadataFilter
  from pipeline.faithfulness_checker import FaithfulnessChecker
  import rag_config
  ```
- [ ] At startup (after Qdrant connection), initialize:
  ```python
  bm25_manager = BM25IndexManager(qdrant_client)
  bm25_manager.load_or_build()
  spell_corrector = SpellCorrector()
  query_rewriter = QueryRewriter(llm_client, supabase)
  hybrid_retriever = HybridRetriever(bm25_manager, qdrant_client, embed_query, "college_knowledgebase")
  faithfulness_checker = FaithfulnessChecker(llm_client)
  ```
- [ ] Update `/api/chat` endpoint flow:
  1. **Step 0** (new): `corrected_query, corrections = spell_corrector.correct(user_message)`
     - Log corrections at DEBUG level
     - Use `corrected_query` for all downstream steps
  2. **Step 1** (existing): intent classification + keyword expansion
     - Extract `category` with confidence from LLM response, pass to retriever if confidence ≥ 0.70
  3. **Step 2** (existing): cache lookup (honour `bypass_cache` field in request body, Req 5.7)
  4. **Step 3** (new): `rewritten_query, was_rewritten = query_rewriter.rewrite(corrected_query, session_id)`
     - Store both `corrected_query` (original) and `rewritten_query` in `chat_messages.metadata` (Req 6.5)
     - Use `rewritten_query` for embedding/retrieval
  5. **Step 4** (replace): `candidates = hybrid_retriever.retrieve(rewritten_query, keywords, category)`
     - Replaces existing `qdrant_client.search()` call
  6. **Step 5** (existing): rerank 40 candidates → top 6
     - Log all logit scores at DEBUG level (Req 4.1)
     - If all logits below `RERANK_SCORE_THRESHOLD` → fallback to top 6 by cosine, log WARN (Req 4.5)
     - Extract `max_rerank_logit = max(logits)` for faithfulness check
  7. **Step 6** (new): `should_replace, invoked, passed = faithfulness_checker.check(answer, context, max_rerank_logit)`
     - If `should_replace == True` → replace answer with fallback message
  8. **Step 7** (existing): LLM generation (only if not cached)
  9. **Step 8** (existing): cache save + response build
- [ ] Build per-request `trace` dict (Design.md Section 8) and store in `chat_messages.metadata`:
  ```python
  trace = {
      "spell_corrections": corrections,
      "was_rewritten": was_rewritten,
      "original_query": corrected_query,
      "rewritten_query": rewritten_query if was_rewritten else None,
      "category_filter": category,
      "bm25_count": len(bm25_results),
      "dense_count": len(dense_results),
      "rrf_count": len(candidates),
      "rerank_logits": logits,
      "max_rerank_logit": max_rerank_logit,
      "rerank_used": rerank_succeeded,
      "faithfulness_check_invoked": invoked,
      "faithfulness_passed": passed,
      "metadata_filter_fallback": filter_fallback_triggered,
  }
  ```
- [ ] Ensure all exceptions are caught gracefully with WARN logs, pipeline never returns 500 to user for retrieval failures

**Files Modified:**
- `api_server.py` (major refactor of `/api/chat` handler)

**Verification:**
```bash
# Start server
python api_server.py

# Test spell correction
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "admision fees for cse", "session_id": "test"}'

# Check logs for:
# - [SpellCorrector] corrections
# - [HybridRetriever] BM25 + dense counts
# - [Reranker] logit scores
# - Response metadata contains trace
```

---

### Task 3.6: Add `/api/debug/rerank` Diagnostic Endpoint

**Status:** `backlog`  
**Requirements:** Req 4.4  
**Design Reference:** Design.md Section 5 (API contracts)

**Description:**  
Create a debug endpoint that accepts raw query + passages and returns reranker scores for manual diagnostic testing.

**Acceptance Criteria:**
- [ ] Add `POST /api/debug/rerank` endpoint to `api_server.py`
- [ ] Request schema:
  ```python
  class DebugRerankRequest(BaseModel):
      query: str
      passages: list[str]  # 1-100 passages
  ```
- [ ] Response schema:
  ```python
  {
      "query": str,
      "results": [
          {"passage": str, "index": int, "logit": float},
          ...
      ]
  }
  ```
- [ ] Call NVIDIA rerank API directly with provided passages, return raw logits
- [ ] No caching, no filtering — pure diagnostic tool
- [ ] Return HTTP 400 if `passages` list is empty or >100 items
- [ ] Log all calls to this endpoint at INFO level (includes query + passage count)

**Files Modified:**
- `api_server.py`

**Verification:**
```bash
curl -X POST http://localhost:8000/api/debug/rerank \
  -H "Content-Type: application/json" \
  -d '{
    "query": "CSE admission fees",
    "passages": [
      "CSE offers 180 seats with fees of Rs. 2,00,000 per year",
      "The hostel provides accommodation for students",
      "Computer Science Engineering has excellent placement records"
    ]
  }'

# Expected: JSON with 3 results, each with logit score
```

---

### Task 3.7: Add `/api/feedback` Endpoint for User Ratings

**Status:** `backlog`  
**Requirements:** Req 9.2, Req 9.3, Req 9.4, Req 9.7  
**Design Reference:** Design.md Section 5 (API contracts), Section 4 (schema)

**Description:**  
Create an endpoint that accepts thumbs-up/down feedback on assistant messages and stores it in Supabase.

**Acceptance Criteria:**
- [ ] Add `POST /api/feedback` endpoint to `api_server.py`
- [ ] Request schema:
  ```python
  class FeedbackRequest(BaseModel):
      message_id: str  # UUID
      session_id: str  # UUID
      rating: int      # -1 or 1
  ```
- [ ] Response schemas:
  - Success: `{"status": "ok"}` (HTTP 200)
  - Message not found: `{"error": "message not found"}` (HTTP 404)
  - Invalid rating: `{"error": "rating must be -1 or 1"}` (HTTP 422)
- [ ] Validation logic:
  - Check `rating IN (-1, 1)` before DB call → return 422 if invalid (Req 9.4, fixes missing gap)
  - Query `chat_messages` for `message_id` → return 404 if not exists (Req 9.3)
- [ ] Insert with upsert:
  ```sql
  INSERT INTO message_feedback (message_id, session_id, rating)
  VALUES (%s, %s, %s)
  ON CONFLICT (message_id) DO UPDATE 
    SET rating = EXCLUDED.rating, 
        created_at = CURRENT_TIMESTAMP
  ```
- [ ] Log feedback submissions at INFO level: `[Feedback] message={message_id} rating={rating}`

**Files Modified:**
- `api_server.py`

**Verification:**
```bash
# Get a real message_id from chat_messages table first
MESSAGE_ID="<uuid-from-db>"

# Submit thumbs up
curl -X POST http://localhost:8000/api/feedback \
  -H "Content-Type: application/json" \
  -d "{\"message_id\": \"$MESSAGE_ID\", \"session_id\": \"test-session\", \"rating\": 1}"

# Verify in DB
psql $DATABASE_URL -c "SELECT * FROM message_feedback WHERE message_id = '$MESSAGE_ID';"

# Test error cases
curl -X POST http://localhost:8000/api/feedback \
  -d '{"message_id": "nonexistent-uuid", "session_id": "test", "rating": 1}'
# Expected: 404

curl -X POST http://localhost:8000/api/feedback \
  -d '{"message_id": "'$MESSAGE_ID'", "session_id": "test", "rating": 5}'
# Expected: 422
```


---

## Phase 4: Evaluation Harness

### Task 4.1: Create Ground-Truth Evaluation Dataset

**Status:** `backlog`  
**Requirements:** Req 5.1, Req 5.2, Req 5.8  
**Design Reference:** Design.md Section 3.4 (EvalHarness stub)

**Description:**  
Build a curated dataset of 30-50 real questions with expected answers and source metadata for objective pipeline evaluation.

**Acceptance Criteria:**
- [ ] Create directory `eval/`
- [ ] Create `eval/eval_dataset.json` with schema:
  ```json
  [
    {
      "question": "What are the admission fees for CSE?",
      "expected_answer": "The tuition fee for B.E Computer Science Engineering is Rs. 2,00,000 per year.",
      "category": "Admission & Fees",
      "source_file": "msajce_admission.pdf",
      "has_exact_identifier": false
    },
    ...
  ]
  ```
- [ ] Include 30-50 questions total
- [ ] Cover at least 8 distinct categories from Qdrant collection
- [ ] Include at least 5 questions with exact identifiers: course codes (e.g., "MA3303"), bus routes (e.g., "AR 8"), staff names (Req 5.8)
- [ ] For exact-identifier questions, set `has_exact_identifier: true` for separate metric tracking
- [ ] Each question should have a verifiable expected answer found in the source PDF
- [ ] Questions should represent real user queries (from logs if available, or synthetically realistic)

**Files Created:**
- `eval/eval_dataset.json`

**Verification:**
```python
import json
with open("eval/eval_dataset.json") as f:
    dataset = json.load(f)
assert 30 <= len(dataset) <= 50
categories = {q["category"] for q in dataset}
assert len(categories) >= 8
exact_id_count = sum(1 for q in dataset if q.get("has_exact_identifier"))
assert exact_id_count >= 5
print(f"✓ Dataset: {len(dataset)} questions, {len(categories)} categories, {exact_id_count} exact-ID queries")
```

---

### Task 4.2: Implement `run_eval.py` Metrics Harness

**Status:** `backlog`  
**Requirements:** Req 5.3, Req 5.4, Req 5.5, Req 5.6, Req 5.7  
**Design Reference:** Design.md Section 3.4 (EvalHarness), Section 5 (bypass_cache)

**Description:**  
Create a CLI script that runs all eval questions through the pipeline and computes Recall@6, Exact Match, and F1 metrics.

**Acceptance Criteria:**
- [ ] Create `eval/run_eval.py` with CLI interface
- [ ] Command-line flags:
  - `--dataset` (default: `eval/eval_dataset.json`)
  - `--output` (default: `eval/results_{timestamp}.json`)
  - `--bypass-cache` (flag, passes `bypass_cache: true` in request body per Req 5.7)
  - `--pipeline-variant` (optional string tag for comparison runs, Req 5.6)
- [ ] For each question in dataset:
  - Call `POST /api/chat` with `{"message": question, "bypass_cache": bypass_cache_flag}`
  - Extract returned `citations` (list of source chunks)
  - Compute metrics:
    - **Recall@6**: Does any citation's `source_file` match the expected `source_file`? (binary: 0 or 1)
    - **Answer EM**: Does generated answer exactly match expected answer? (case-insensitive, whitespace-normalized)
    - **Answer F1**: Token-level overlap F1 between generated and expected answers (tokenize by whitespace, compute precision/recall/F1)
- [ ] Write per-question results to JSON:
  ```json
  {
    "timestamp": "2026-07-25T10:30:00Z",
    "pipeline_variant": "baseline",
    "bypass_cache": true,
    "questions": [
      {
        "question": "...",
        "expected_answer": "...",
        "generated_answer": "...",
        "category": "...",
        "source_file": "...",
        "has_exact_identifier": false,
        "recall_at_6": 1,
        "answer_em": 0,
        "answer_f1": 0.73,
        "latency_ms": 1450
      },
      ...
    ],
    "aggregate": {
      "mean_recall_at_6": 0.82,
      "mean_answer_em": 0.14,
      "mean_answer_f1": 0.61,
      "exact_identifier_recall": 0.90,
      "mean_latency_ms": 1523
    }
  }
  ```
- [ ] Print summary table to stdout:
  ```
  ========================================
  Evaluation Results (50 questions)
  ========================================
  Recall@6:         82.0%
  Answer EM:        14.0%
  Answer F1:        61.0%
  Exact ID Recall:  90.0%
  Mean Latency:     1523 ms
  ========================================
  ```
- [ ] Complete full 50-question eval within 10 minutes (Req 5.5)
- [ ] Handle API errors gracefully: if a question fails, log error and continue with next question

**Files Created:**
- `eval/run_eval.py`

**Verification:**
```bash
# Ensure API server running
python api_server.py &

# Run baseline eval
python eval/run_eval.py --bypass-cache --pipeline-variant baseline

# Check output file created
ls -lh eval/results_*.json

# Run again with different variant for comparison
python eval/run_eval.py --bypass-cache --pipeline-variant with_hybrid_search
```

---

### Task 4.3: Update `api_server.py` to Honor `bypass_cache` Field

**Status:** `backlog`  
**Requirements:** Req 5.7  
**Design Reference:** Design.md Section 5 (ChatRequest schema)

**Description:**  
Modify `/api/chat` to accept an optional `bypass_cache` boolean in the request body and skip cache lookup when set.

**Acceptance Criteria:**
- [ ] Update `ChatRequest` Pydantic model:
  ```python
  class ChatRequest(BaseModel):
      message: str
      session_id: str | None = None
      bypass_cache: bool = False  # NEW
  ```
- [ ] In `/api/chat` handler, wrap cache lookup:
  ```python
  if not request.bypass_cache:
      cached = check_cache(query_hash)
      if cached:
          return cached
  # ... continue with retrieval ...
  ```
- [ ] Cache write still happens at end (even if `bypass_cache=True` on read) so that other users benefit
- [ ] Do NOT modify query string or query_hash when `bypass_cache=True` (Req 5.7 — must not affect retrieval semantics)
- [ ] Log at DEBUG level when cache is bypassed: `[Cache] Bypassed for query_hash={hash}`

**Files Modified:**
- `api_server.py`

**Verification:**
```bash
# Run query twice with caching
curl -X POST http://localhost:8000/api/chat \
  -d '{"message": "CSE admission fees", "session_id": "test"}'
# Second call should be cached (isCached: true)

# Run with bypass_cache
curl -X POST http://localhost:8000/api/chat \
  -d '{"message": "CSE admission fees", "session_id": "test", "bypass_cache": true}'
# Should NOT return cached result (isCached: false), but still hit pipeline
```

---

## Phase 5: Frontend Feedback UI

### Task 5.1: Extend TypeScript Types for Feedback

**Status:** `backlog`  
**Requirements:** Req 9.4, Req 9.5  
**Design Reference:** Design.md Section 7 (TypeScript interfaces)

**Description:**  
Update the `ChatMessage` interface to include feedback state tracking.

**Acceptance Criteria:**
- [ ] Create or update `src/types/chat.ts` (or inline in `useCampusChat.ts` if no separate types file)
- [ ] Extend `ChatMessage` interface:
  ```typescript
  interface ChatMessage {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: Date;
    citations?: Citation[];
    tokenUsage?: TokenUsage;
    modelUsed?: string;
    isCached?: boolean;
    // NEW fields for feedback
    message_id?: string;        // Backend UUID for feedback submission
    feedbackState?: 'none' | 'thumbs_up' | 'thumbs_down' | 'submitting';
  }
  ```
- [ ] Ensure all components using `ChatMessage` handle optional `feedbackState` field

**Files Modified:**
- `src/types/chat.ts` (or `src/hooks/useCampusChat.ts`)

**Verification:**
```bash
npm run build
# Check no TypeScript errors
```


---

### Task 5.2: Create `FeedbackButtons` Component

**Status:** `backlog`  
**Requirements:** Req 9.4, Req 9.5, Req 9.6  
**Design Reference:** Design.md Section 7 (FeedbackButtons.tsx)

**Description:**  
Create a React component that renders thumbs-up and thumbs-down buttons with submit logic and state management.

**Acceptance Criteria:**
- [ ] Create `src/components/chat/FeedbackButtons.tsx`
- [ ] Component props:
  ```typescript
  interface FeedbackButtonsProps {
    messageId: string;
    sessionId: string;
    feedbackState: 'none' | 'thumbs_up' | 'thumbs_down' | 'submitting';
    onFeedbackSubmit: (messageId: string, rating: -1 | 1) => Promise<void>;
  }
  ```
- [ ] Render two buttons: 👍 (thumbs up, rating=1) and 👎 (thumbs down, rating=-1)
- [ ] Button states:
  - `feedbackState === 'none'` → both buttons enabled, default styling
  - `feedbackState === 'submitting'` → both buttons disabled, show loading spinner
  - `feedbackState === 'thumbs_up'` → thumbs-up button highlighted with checkmark ✓, both disabled
  - `feedbackState === 'thumbs_down'` → thumbs-down button highlighted with checkmark ✓, both disabled
- [ ] On button click → call `onFeedbackSubmit(messageId, rating)`, set local state to `'submitting'`
- [ ] Styling matches Lorin AI design system (OKLCH colors, glassmorphism, hover effects)
- [ ] Buttons appear below message bubble with small gap (8px)

**Files Created:**
- `src/components/chat/FeedbackButtons.tsx`

**Verification:**
```bash
npm run dev
# Manually test clicking thumbs up/down after an assistant message renders
# Verify state changes correctly, buttons disable after submission
```

---

### Task 5.3: Integrate `FeedbackButtons` into `MessageBubble`

**Status:** `backlog`  
**Requirements:** Req 9.4  
**Design Reference:** Design.md Section 7 (MessageBubble integration)

**Description:**  
Add `FeedbackButtons` below assistant message bubbles, only shown after message fully renders.

**Acceptance Criteria:**
- [ ] Import `FeedbackButtons` in `src/components/chat/MessageBubble.tsx`
- [ ] For `role === 'assistant'` messages only:
  - Render `<FeedbackButtons />` below message content
  - Pass props: `messageId={message.message_id}`, `sessionId={sessionId}`, `feedbackState={message.feedbackState}`, `onFeedbackSubmit={handleFeedback}`
- [ ] Only render buttons when:
  - Message content is fully rendered (not still animating)
  - `message.message_id` exists (backend has assigned UUID)
  - For typewriter animation mode: after animation completes
  - For streaming mode: after `event: done` SSE event received (Req 9.4)
- [ ] Pass `handleFeedback` callback down from parent (will be implemented in next task)

**Files Modified:**
- `src/components/chat/MessageBubble.tsx`

**Verification:**
```bash
npm run dev
# Send a message, wait for answer to fully render
# Verify thumbs up/down buttons appear below assistant message
# Verify buttons do NOT appear for user messages
```

---

### Task 5.4: Add Feedback Submission Logic to `useCampusChat`

**Status:** `backlog`  
**Requirements:** Req 9.2, Req 9.5, Req 9.6, Req 9.7  
**Design Reference:** Design.md Section 7 (useCampusChat additions)

**Description:**  
Extend the chat hook to handle feedback submissions, update message state, and call the `/api/feedback` endpoint.

**Acceptance Criteria:**
- [ ] Add `submitFeedback` function to `useCampusChat.ts`:
  ```typescript
  const submitFeedback = async (messageId: string, rating: -1 | 1): Promise<void> => {
    // Find message in state
    const msgIndex = messages.findIndex(m => m.message_id === messageId);
    if (msgIndex === -1) return;

    // Optimistic update: set submitting state
    setMessages(prev => prev.map(m => 
      m.message_id === messageId 
        ? { ...m, feedbackState: 'submitting' } 
        : m
    ));

    try {
      const response = await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message_id: messageId,
          session_id: sessionId,
          rating: rating
        })
      });

      if (!response.ok) {
        throw new Error(`Feedback failed: ${response.status}`);
      }

      // Success: update to final state
      setMessages(prev => prev.map(m => 
        m.message_id === messageId 
          ? { ...m, feedbackState: rating === 1 ? 'thumbs_up' : 'thumbs_down' } 
          : m
      ));
    } catch (error) {
      console.error('[Feedback] Submission failed:', error);
      // Revert to 'none' on error
      setMessages(prev => prev.map(m => 
        m.message_id === messageId 
          ? { ...m, feedbackState: 'none' } 
          : m
      ));
    }
  };
  ```
- [ ] Return `submitFeedback` from hook alongside `messages`, `sendMessage`, etc.
- [ ] Initialize all new assistant messages with `feedbackState: 'none'`
- [ ] Extract `message_id` from API response (`/api/chat` should return it) and store in message object
- [ ] Ensure `sessionId` is available in hook state (from user or auto-generated)

**Files Modified:**
- `src/hooks/useCampusChat.ts`

**Verification:**
```bash
npm run dev
# Send message, wait for answer
# Click thumbs up → verify network request to /api/feedback
# Check button changes to highlighted state with checkmark
# Refresh page → feedback state should NOT persist (in-session only per Req 9.6)
```

---

### Task 5.5: Update `api_server.py` to Return `message_id` in Chat Response

**Status:** `backlog`  
**Requirements:** Req 9.2 (implicit — frontend needs message_id to submit feedback)  
**Design Reference:** Design.md Section 7 (frontend needs message_id)

**Description:**  
Ensure `/api/chat` response includes the `message_id` (UUID) of the saved assistant message so frontend can reference it for feedback.

**Acceptance Criteria:**
- [ ] After saving assistant message to `chat_messages` table, extract the inserted row's `id` (UUID)
- [ ] Add `message_id` field to `ChatResponse` schema:
  ```python
  class ChatResponse(BaseModel):
      answer: str
      citations: list[dict]
      modelUsed: str
      isCached: bool
      tokenUsage: dict
      message_id: str  # NEW — UUID of assistant message in DB
  ```
- [ ] Return `message_id` in response JSON
- [ ] For cached responses, return the original message_id from cache metadata

**Files Modified:**
- `api_server.py`

**Verification:**
```bash
curl -X POST http://localhost:8000/api/chat \
  -d '{"message": "test", "session_id": "test-session"}' | jq '.message_id'
# Should print a UUID
```

---

## Phase 6: Lower-Priority Features

### Task 6.1: Implement Query Decomposition for Compound Questions

**Status:** `backlog`  
**Requirements:** Req 10a.1, Req 10a.2  
**Design Reference:** Design.md Section 10 (future work)

**Description:**  
Add LLM-based detection and decomposition of compound queries (e.g., "What are the CSE fees and hostel facilities?") into multiple sub-questions, with independent retrieval and merged answers.

**Acceptance Criteria:**
- [ ] Create `pipeline/query_decomposer.py` with `QueryDecomposer` class
- [ ] Method `decompose(query)` returns `(is_compound: bool, sub_questions: list[str])`
- [ ] Use LLM to detect compound queries and split into up to 3 sub-questions (Req 10a.2)
- [ ] If compound detected:
  - Run full pipeline independently for each sub-question
  - Merge answers into single coherent response with section headings per sub-question
- [ ] Add intent type `"compound_query"` to intent classifier
- [ ] Log decomposition at INFO level: `[Decomposer] Split query into {n} sub-questions`

**Files Created:**
- `pipeline/query_decomposer.py`

**Files Modified:**
- `api_server.py` (add decomposition step before retrieval)

**Verification:**
```bash
curl -X POST http://localhost:8000/api/chat \
  -d '{"message": "What are the CSE admission fees and hostel charges?", "session_id": "test"}'
# Check logs for decomposition
# Verify answer addresses both sub-questions
```


---

### Task 6.2: Implement SSE Streaming for `/api/chat/stream`

**Status:** `backlog`  
**Requirements:** Req 10b.3, Req 10b.4, Req 10b.5  
**Design Reference:** Design.md Section 5 (API contracts), Section 7 (frontend streaming)

**Description:**  
Add Server-Sent Events endpoint that streams LLM tokens as they're generated, with final `done` event containing citations and metadata.

**Acceptance Criteria:**
- [ ] Create `POST /api/chat/stream` endpoint in `api_server.py`
- [ ] Accept same `ChatRequest` body as `/api/chat`
- [ ] Return `Content-Type: text/event-stream`
- [ ] Stream format:
  ```
  data: {"type": "token", "content": "The "}
  
  data: {"type": "token", "content": "CSE "}
  
  data: {"type": "token", "content": "admission "}
  
  event: done
  data: {"type": "done", "citations": [...], "tokenUsage": {...}, "message_id": "..."}
  ```
- [ ] Use NVIDIA API streaming mode if available, else chunk non-streaming response by words
- [ ] Frontend: update `useCampusChat.ts` to accept `streaming: bool` option
- [ ] When `streaming=true`, connect to `/api/chat/stream` via EventSource API, append tokens to message content in real-time
- [ ] After `done` event, populate `citations`, `tokenUsage`, `message_id` fields and show FeedbackButtons (Req 10b.5, Req 9.4)

**Files Modified:**
- `api_server.py` (new endpoint)
- `src/hooks/useCampusChat.ts` (add streaming mode)

**Verification:**
```bash
# Terminal 1: start server
python api_server.py

# Terminal 2: test with curl
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "CSE admission fees", "session_id": "test"}'

# Should see token-by-token output, then done event

# Frontend test:
npm run dev
# Enable streaming in useCampusChat config
# Send message, verify typewriter effect from server stream
```

---

### Task 6.3: Add `--incremental` Flag to `process_dataset.py`

**Status:** `backlog`  
**Requirements:** Req 10c.6, Req 10c.7, Req 10c.8  
**Design Reference:** Design.md Section 10 (incremental reindex)

**Description:**  
Support incremental re-indexing where only PDFs with updated modification timestamps are re-processed, with automatic cleanup of stale chunks.

**Acceptance Criteria:**
- [ ] Add `--incremental` CLI flag to `process_dataset.py`:
  ```python
  parser.add_argument('--incremental', action='store_true',
                      help='Only process PDFs changed since last run')
  ```
- [ ] Track last successful run timestamp in Supabase `scraped_documents` table (add `updated_at` column if not exists)
- [ ] When `--incremental` is set:
  - Query `scraped_documents` for each PDF's `updated_at` timestamp
  - Compare with filesystem `mtime` (modification time)
  - Skip PDFs where `mtime <= updated_at`
  - Log: `[Incremental] Skipping {pdf_name}, unchanged since {updated_at}`
- [ ] Before upserting new chunks for a changed PDF:
  - Delete all existing Qdrant points with `payload["source_file"] == pdf_name` (Req 10c.7)
  - Log: `[Incremental] Deleted {n} stale chunks for {pdf_name}`
- [ ] After successful indexing, update `scraped_documents.updated_at = CURRENT_TIMESTAMP` for processed PDFs
- [ ] Environment variable validation (Req 10c.8):
  ```python
  required_env = ["NVIDIA_API_KEY", "QDRANT_URL", "QDRANT_API_KEY", "DATABASE_URL"]
  missing = [k for k in required_env if not os.getenv(k)]
  if missing:
      print(f"ERROR: Missing required environment variables: {missing}", file=sys.stderr)
      sys.exit(1)
  ```
- [ ] Exit code 0 on success, non-zero on any error

**Files Modified:**
- `process_dataset.py`
- `schema.sql` (add `updated_at` column to `scraped_documents` if needed)

**Verification:**
```bash
# Initial full index
python process_dataset.py

# Touch one PDF to update mtime
touch dataset/msajce_about.pdf

# Run incremental
python process_dataset.py --incremental
# Check logs: should process only msajce_about.pdf, skip others

# Verify stale chunks deleted
# Query Qdrant for source_file="msajce_about.pdf", verify only new chunks present
```

---

### Task 6.4: Add Category List to `rag_config.py` for Discoverability

**Status:** `backlog`  
**Requirements:** Req 2.4  
**Design Reference:** Design.md Section 6 (config constants)

**Description:**  
Export the list of valid category values from `rag_config.py` so that metadata filter logic can validate categories without hardcoding.

**Acceptance Criteria:**
- [ ] Add to `rag_config.py`:
  ```python
  VALID_CATEGORIES = [
      "About MSAJCE",
      "Admission & Fees",
      "Departments",
      "Hostel",
      "Transport",
      "Placement",
      "Library",
      "Sports & Clubs",
      "Alumni",
      "Research & Innovation",
      # ... complete list from all PDFs
  ]
  ```
- [ ] Populate list by querying Qdrant for distinct `payload["category"]` values or manually curating from dataset
- [ ] Update `MetadataFilter` to import and validate against `VALID_CATEGORIES`
- [ ] Log warning if inferred category not in valid list: `[MetadataFilter] Unknown category '{category}', skipping filter`

**Files Modified:**
- `rag_config.py`
- `pipeline/metadata_filter.py` (add validation)

**Verification:**
```python
import rag_config
assert len(rag_config.VALID_CATEGORIES) >= 8
print(f"✓ {len(rag_config.VALID_CATEGORIES)} valid categories defined")
```

---

## Cross-Phase Tasks

### Task X.1: Update `requirements.txt` with All New Dependencies

**Status:** `backlog`  
**Requirements:** All (dependencies for new pipeline components)  
**Design Reference:** Design.md Section 2.1

**Description:**  
Ensure all Python packages required by new pipeline components are listed in `requirements.txt`.

**Acceptance Criteria:**
- [ ] Add to `requirements.txt`:
  ```
  rank-bm25>=0.2.2
  python-Levenshtein>=0.21.0
  ```
- [ ] Verify existing dependencies still present: `qdrant-client`, `supabase`, `fastapi`, `pydantic`, etc.
- [ ] Test clean install in fresh virtualenv:
  ```bash
  python -m venv test_env
  source test_env/bin/activate  # or test_env\Scripts\activate on Windows
  pip install -r requirements.txt
  python -c "import rank_bm25, Levenshtein; print('✓ All imports successful')"
  ```

**Files Modified:**
- `requirements.txt`

**Verification:**
```bash
pip install -r requirements.txt
python -c "from pipeline.spell_corrector import SpellCorrector; from pipeline.bm25_index_manager import BM25IndexManager; print('✓')"
```

---

### Task X.2: Add Logging Configuration for All Pipeline Components

**Status:** `backlog`  
**Requirements:** Req 1.7, Req 3.8, Req 4.1, Req 6.6, Req 7.4, Req 8.7  
**Design Reference:** Design.md Section 3 (all components use logging)

**Description:**  
Standardize logging across all pipeline modules with consistent format and appropriate levels.

**Acceptance Criteria:**
- [ ] Add to `api_server.py` startup:
  ```python
  import logging
  logging.basicConfig(
      level=logging.DEBUG if os.getenv("DEBUG") else logging.INFO,
      format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
      datefmt='%Y-%m-%d %H:%M:%S'
  )
  ```
- [ ] All pipeline modules use `logger = logging.getLogger(__name__)`
- [ ] Log levels used correctly:
  - **DEBUG**: spell corrections, rerank logits, BM25 counts, RRF fusion details
  - **INFO**: per-PDF chunk stats, BM25 rebuild events, feedback submissions, decomposition
  - **WARN**: fallbacks (reranker failure, metadata filter fallback, LLM timeouts, BM25 exceptions)
  - **ERROR**: critical failures that should never happen in production
- [ ] No sensitive data logged (API keys, user PII, full query cache contents)
- [ ] Logs include enough context to diagnose issues: `{component} {action} {key_data}`

**Files Modified:**
- `api_server.py` (logging setup)
- All `pipeline/*.py` files (standardize logger usage)

**Verification:**
```bash
# Run with debug logging
DEBUG=1 python api_server.py

# Send test request
curl -X POST http://localhost:8000/api/chat -d '{"message": "test"}'

# Check logs contain:
# - [SpellCorrector] corrections
# - [HybridRetriever] BM25 + dense counts
# - [Reranker] logit scores
# - [FaithfulnessChecker] invocation/skip decisions
```

---

### Task X.3: Create Integration Test Suite

**Status:** `backlog`  
**Requirements:** All (end-to-end validation)  
**Design Reference:** Design.md Section 9 (implementation order)

**Description:**  
Build a pytest-based integration test suite that validates the full pipeline with real components (not mocks).

**Acceptance Criteria:**
- [ ] Create `tests/` directory with `test_integration.py`
- [ ] Tests require real services (Qdrant, Supabase, NVIDIA API) — use test environment variables
- [ ] Test cases:
  - `test_spell_correction_e2e()` — query with typo returns corrected results
  - `test_hybrid_retrieval()` — exact identifier query (e.g., "AR 8 bus route") found via BM25
  - `test_metadata_filter()` — category-specific query only returns chunks from that category
  - `test_query_rewrite()` — follow-up question in multi-turn session gets rewritten
  - `test_faithfulness_check()` — low-confidence query triggers check, high-confidence skips it
  - `test_feedback_submission()` — thumbs up/down stored in DB correctly
  - `test_incremental_reindex()` — only changed PDFs re-processed
- [ ] Each test asserts on multiple criteria (returned answer, log messages, DB state, trace metadata)
- [ ] Run via `pytest tests/` with clean teardown between tests

**Files Created:**
- `tests/__init__.py`
- `tests/test_integration.py`
- `tests/conftest.py` (pytest fixtures for clients)

**Verification:**
```bash
pytest tests/ -v --tb=short
# All tests should pass
```


---

## Summary: Task Dependency Graph

```
Phase 1 (Foundation)
├── Task 1.1: rag_config.py ────────────────────────┐
├── Task 1.2: DB schema migrations ─────────────────┤
├── Task 1.3: SemanticChunker ──────────────────────┤
└── Task 1.4: Update process_dataset.py ────────────┤
                                                     │
Phase 2 (BM25 + Spell)                              │
├── Task 2.1: BM25IndexManager ─────────────────────┤
├── Task 2.2: SpellCorrector ───────────────────────┤
├── Task 2.3: BM25 rebuild vocab hook ──────────────┤
└── Task 2.4: process_dataset BM25 trigger ─────────┤
                                                     │
Phase 3 (Pipeline Integration)                      ├─ All feed into Phase 3
├── Task 3.1: MetadataFilter ───────────────────────┤
├── Task 3.2: HybridRetriever ──────────────────────┤
├── Task 3.3: QueryRewriter ────────────────────────┤
├── Task 3.4: FaithfulnessChecker ──────────────────┤
├── Task 3.5: Integrate into api_server.py ─────────┘
├── Task 3.6: /api/debug/rerank endpoint
└── Task 3.7: /api/feedback endpoint

Phase 4 (Evaluation)
├── Task 4.1: eval_dataset.json
├── Task 4.2: run_eval.py
└── Task 4.3: bypass_cache support

Phase 5 (Frontend)
├── Task 5.1: TypeScript types
├── Task 5.2: FeedbackButtons component
├── Task 5.3: Integrate into MessageBubble
├── Task 5.4: useCampusChat feedback logic
└── Task 5.5: api_server return message_id

Phase 6 (Lower Priority)
├── Task 6.1: Query decomposition
├── Task 6.2: SSE streaming
├── Task 6.3: --incremental flag
└── Task 6.4: Category list in config

Cross-Phase
├── Task X.1: requirements.txt
├── Task X.2: Logging configuration
└── Task X.3: Integration tests
```

---

## Implementation Notes

### Recommended Start Order

1. **Week 1** — Phase 1 + Phase 2 (foundation, chunking, BM25, spell)
   - Tasks 1.1 → 1.4, then 2.1 → 2.4
   - Run baseline eval with old pipeline before changes

2. **Week 2** — Phase 3 (core pipeline integration)
   - Tasks 3.1 → 3.7
   - This is the highest-risk phase — test thoroughly after each task

3. **Week 3** — Phase 4 + Phase 5 (eval + frontend)
   - Tasks 4.1 → 4.3, then 5.1 → 5.5
   - Run comparative evals: before vs. after improvements

4. **Week 4** — Phase 6 + Cross-Phase (polish)
   - Tasks 6.1 → 6.4, X.1 → X.3
   - Only implement Phase 6 tasks if time allows

### Risk Mitigation

- **High-risk tasks** (major pipeline changes):
  - Task 3.5 (api_server integration) — stage and test incrementally
  - Task 2.1 (BM25IndexManager) — validate pkl persistence carefully
  - Task 1.3 (SemanticChunker) — test on variety of PDFs, check chunk quality manually

- **Rollback strategy**:
  - Keep old `process_dataset.py` chunking logic in a `_legacy` branch
  - Feature-flag new pipeline components in `api_server.py` with env var `USE_NEW_PIPELINE=1`
  - If production issues arise, disable flag and investigate offline

### Testing Strategy

- **Unit tests**: Each pipeline component in `tests/unit/test_*.py`
- **Integration tests**: Full pipeline flow in `tests/test_integration.py` (Task X.3)
- **Eval harness**: Quantitative metrics with `eval/run_eval.py` (Task 4.2)
- **Manual QA**: Test with real user queries from logs, especially edge cases

### Definition of Done (Per Task)

- [ ] Code written and passes linting (`black`, `mypy` for Python; `prettier`, `eslint` for TypeScript)
- [ ] Verification commands in task checklist all pass
- [ ] Unit tests added if applicable
- [ ] Integration test updated if task affects end-to-end flow
- [ ] Documentation updated (`README.md` or inline docstrings)
- [ ] Merged to main branch after code review

---

## Appendix: Acceptance Criteria Cross-Reference

This table maps each requirement to the task(s) that implement it:

| Requirement | Tasks |
|-------------|-------|
| Req 1 (Chunking) | 1.1, 1.3, 1.4 |
| Req 2 (Metadata Filter) | 1.1, 3.1, 3.5, 6.4 |
| Req 3 (Hybrid Search) | 1.1, 2.1, 2.3, 2.4, 3.2, 3.5 |
| Req 4 (Reranker Verification) | 1.1, 3.5, 3.6 |
| Req 5 (Eval Harness) | 4.1, 4.2, 4.3 |
| Req 6 (Query Rewrite) | 1.1, 3.3, 3.5 |
| Req 7 (Spell Correction) | 1.1, 2.2, 2.3, 3.5 |
| Req 8 (Faithfulness Check) | 1.1, 1.2, 3.4, 3.5 |
| Req 9 (Feedback) | 1.2, 3.7, 5.1, 5.2, 5.3, 5.4, 5.5 |
| Req 10a (Decomposition) | 6.1 |
| Req 10b (Streaming) | 6.2 |
| Req 10c (Incremental) | 6.3 |

---

**Total Tasks:** 30 (excluding sub-tasks)  
**Estimated Effort:** 3-4 weeks (1 developer, full-time)  
**Critical Path:** Phase 1 → Phase 2 → Phase 3 → Phase 4

**Next Steps:** Start with Task 1.1 (rag_config.py) — no dependencies, quick win to establish foundation.
