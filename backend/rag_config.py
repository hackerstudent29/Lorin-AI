"""
RAG Model Registry & Configuration
Strictly enforces budget models for Generation, Embedding, and Re-ranking.
"""

# --- Approved Generation Models (Vercel AI Gateway) ---
GENERATION_MODELS = {
    "PRIMARY": "google/gemini-2.5-flash-lite",   # 1M context, $0.10/M input, 291 tps
    "CACHED_FAQ": "alibaba/qwen3.5-flash",       # $0.10/M input, $0.00 read cache
    "CHEAPEST_INPUT": "openai/gpt-5-nano",       # $0.05/M input, 400K context
    "BUDGET_FLASH": "zai/glm-4.7-flash",         # $0.07/M input, 200K context
    "HIGH_SPEED": "google/gemma-4-31b-it"        # $0.14/M input, 839 tps
}

# --- Approved Embedding Models ---
EMBEDDING_MODELS = {
    "PRIMARY_NVIDIA": "nvidia/nemotron-3-embed-1b", # Free via NVIDIA Nim (2048-dim)
    "VERCEL_CHEAPEST": "alibaba/qwen3-embedding-0.6b", # $0.01/M via Vercel AI Gateway
    "VERCEL_TITAN": "amazon/titan-embed-text-v2",     # $0.02/M via Vercel AI Gateway
    "VERCEL_GOOGLE": "google/text-embedding-005"       # $0.03/M via Vercel AI Gateway
}

# --- Approved Re-Ranking Models ---
RERANK_MODELS = {
    "PRIMARY_NVIDIA": "nvidia/llama-nemotron-rerank-1b-v2", # Free via NVIDIA Nim
    "VERCEL_CHEAPEST": "voyage/rerank-2.5-lite"            # $0.02/M via Vercel AI Gateway
}

# ── Chunking ──────────────────────────────────────────────────────────────────
CHUNK_MIN = 60          # Hard minimum chars of non-whitespace text per chunk
CHUNK_MAX = 900         # Hard maximum chars per chunk
CHUNK_SOFT = 600        # Soft target chars per chunk
OVERLAP_MIN = 60        # Minimum overlap chars from previous chunk
OVERLAP_MAX = 100       # Maximum overlap chars from previous chunk
TABLE_MAX_SINGLE = 1800 # Max chars to keep a table as a single chunk

# ── Category list ─────────────────────────────────────────────────────────────
CATEGORY_LIST = [
    "Department — Computer Science & Engineering",
    "Department — CS & Business Systems",
    "Department — CS & Cyber Security",
    "Department — AI & Data Science",
    "Department — AI & Machine Learning",
    "Department — Information Technology",
    "Department — Electronics & Communication",
    "Department — Electrical & Electronics",
    "Department — Mechanical Engineering",
    "Department — Civil Engineering",
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

VALID_CATEGORIES = CATEGORY_LIST  # alias for MetadataFilter validation (Req 2.4)

CATEGORY_CONFIDENCE_THRESHOLD = 0.90  # Min LLM confidence to apply metadata filter (raised to avoid false filtering)

# ── Hybrid retrieval ──────────────────────────────────────────────────────────
BM25_TOP_K = 25          # Number of BM25 candidates retrieved
DENSE_TOP_K = 25         # Number of dense vector candidates retrieved
RRF_K = 60               # RRF constant k in 1/(k+rank)
RRF_OUTPUT_SIZE = 40     # Max merged candidates after RRF fusion
MIN_CATEGORY_HITS = 5    # Min filtered hits before falling back to unfiltered

# ── Re-ranking ────────────────────────────────────────────────────────────────
RERANK_TOP_N = 5                  # Chunks kept after re-ranking
RERANK_SCORE_THRESHOLD = -15.0    # Minimum logit score to include chunk (NVIDIA logit scale ~-20 to +5)

# ── Query rewriting ───────────────────────────────────────────────────────────
REWRITE_MIN_HISTORY_TURNS = 1    # Min prior assistant turns needed to trigger rewrite (1 = fires after first exchange)
REWRITE_MAX_CONTEXT_TURNS = 4    # How many prior turns to include in rewrite prompt

# ── Spell correction ──────────────────────────────────────────────────────────
SPELL_MIN_FREQ = 1           # Minimum corpus frequency for a correction candidate
SPELL_MAX_EDIT_DIST = 2      # Maximum Levenshtein edit distance allowed
SPELL_TIMEOUT_MS = 50        # Max allowed processing time in milliseconds

# ── Faithfulness check ────────────────────────────────────────────────────────
# IMPORTANT: NVIDIA reranker returns raw logits in the range ~-20 to +5.
# A logit of -8.0 means "very low confidence retrieval" in this scale.
# Originally set to 0.30 (sigmoid scale) which caused false positives on EVERY query.
FAITHFULNESS_TRIGGER_THRESHOLD = -8.0  # Max rerank logit to trigger check (raw logit scale)
FAITHFULNESS_TIMEOUT_SEC = 10          # Timeout for faithfulness LLM call

# ── Feedback ──────────────────────────────────────────────────────────────────
FEEDBACK_VALID_RATINGS = [-1, 1]  # Allowed rating values
