"""
SemanticChunker — Requirement 1 compliant chunker.
Splits at paragraph, section, or table-row boundaries — never mid-sentence.
"""
import hashlib, re, logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Constants (mirrored from rag_config to keep chunker self-contained) ────────
CHUNK_MIN        = 60
CHUNK_MAX        = 900
CHUNK_SOFT       = 600
OVERLAP_MIN      = 60
OVERLAP_MAX      = 100
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
    title: str = "MSAJCE Campus Document"
    url: str = "https://www.msajce-edu.in"
    department: str = "General"
    document_type: str = "website"
    chunk_index: int = 0
    total_chunks: int = 1
    scraped_at: str = "2026-04-28T00:00:00Z"
    entities: list = field(default_factory=list)
    keywords: list = field(default_factory=list)
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
    def _detect_table_block(lines: list) -> list:
        """
        Return list of (start_idx, end_idx) ranges that are table blocks.
        A table block: >= 3 consecutive lines each with >= 2 tab- or 2+space-aligned columns.
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
        """Return last 60-100 chars of text ending at a sentence boundary."""
        target = min(OVERLAP_MAX, max(OVERLAP_MIN, len(text) // 5))
        suffix = text[-target * 2:]
        sentences = SENTENCE_END_RE.split(suffix)
        overlap = sentences[-1] if sentences else suffix
        return overlap[:OVERLAP_MAX]

    # ── Long paragraph splitter ───────────────────────────────────────────────

    @staticmethod
    def _split_long_para(para: str) -> list:
        """
        Split a paragraph > CHUNK_MAX at nearest sentence end keeping
        both parts >= 200 chars (Req 1.4).
        """
        parts = SENTENCE_END_RE.split(para)
        segments = []
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

    def _chunk_table(self, lines: list, title: str, meta: dict) -> list:
        """Keep table whole if <= TABLE_MAX_SINGLE, else split by rows with header."""
        header_prefix = f"## {title}\n\n" if title != "Overview" else ""
        full_text = header_prefix + "\n".join(lines)

        if len(full_text) <= TABLE_MAX_SINGLE:
            c = full_text.strip()
            if len(c) >= CHUNK_MIN:
                return [Chunk(text=c, section_title=title, **meta)]
            return []

        # Split between complete rows, repeat header row
        header_row = lines[0]
        chunks = []
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

    def chunk_section(self, title: str, body: str, meta: dict) -> list:
        """
        Chunk a single section body into Chunk objects.
        meta contains: source_file, category, page_number, parent_id
        """
        lines = body.splitlines()
        table_ranges = self._detect_table_block(lines)

        chunks = []
        segments = []  # list of {"type": "para"|"table", "content": str|list}

        para_lines = []
        i = 0
        while i < len(lines):
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
                overlap_text = ""
                continue

            # Paragraph chunking
            paragraphs = re.split(r"\n{2,}", seg["content"])
            current = header_prefix + (overlap_text + "\n\n" if overlap_text else "")

            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                sub_paras = self._split_long_para(para) if len(para) > CHUNK_MAX else [para]
                for sp in sub_paras:
                    if len(current) + len(sp) + 2 <= CHUNK_SOFT:
                        current += sp + "\n\n"
                    else:
                        stripped = current.strip()
                        if len(stripped) >= CHUNK_MIN:
                            overlap_text = self._extract_overlap(stripped)
                            chunks.append(Chunk(text=stripped, section_title=title, **meta))
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
                chunks[-1] = Chunk(text=merged, section_title=prev.section_title, **meta)

        return chunks

    # ── Full document chunking ────────────────────────────────────────────────

    def chunk_document(
        self,
        text: str,
        source_file: str,
        category: str,
        page_number: int,
        parent_id: str,
    ) -> list:
        """Top-level entry: split text into sections, then chunk each."""
        meta = dict(
            source_file=source_file,
            category=category,
            page_number=page_number,
            parent_id=parent_id,
        )
        sections = split_into_sections(text)
        all_chunks = []
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


def split_into_sections(text: str) -> list:
    """Split cleaned document text into logical sections by heading detection."""
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
