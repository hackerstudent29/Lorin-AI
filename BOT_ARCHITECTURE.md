# MSAJCE Chatbot (Lorin AI) – End-to-End Pipeline & Architecture Specifications

This document provides a highly detailed, developer-level architectural overview of the Mohamed Sathak A.J. College of Engineering (MSAJCE) Chatbot system.

---

## 1. Technical Stack & Infrastructural Layout

### Frontend Architecture
- **Framework**: React 18+ with TypeScript (Vite-scaffolded).
- **Styling**: TailwindCSS utility framework alongside customized Vanilla CSS selectors for interactive states.
- **Animations**: Framer Motion for smooth message entry, typing state indicators, and bubble scaling.
- **Session Identity**: Automatic UUID v4 client-side generator stored in `localStorage` (`msajce_chat_session_id`) to track multi-turn conversations:
  ```typescript
  const newId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
  ```

### Backend Services
- **Application Framework**: FastAPI (ASGI) running on Python 3.10+.
- **ASGI Server**: Uvicorn.
- **Rate Limiting**: `slowapi` extension injecting token-bucket rate limits:
  - Chat queries (`/api/chat`): `10/minute`, `25/day`.
  - User feedback (`/api/feedback`): `10/minute`.

### Database & Vector Engine
- **Relational Storage**: Cloud-hosted PostgreSQL (via Supabase) utilizing pgBouncer on port `6543`.
- **Vector Database**: Qdrant Cloud Cluster. Matches embeddings in a single collection named `college_knowledgebase`.
  - **Payload Indexes**: Payload index keys are registered on `source_file`, `category`, and `entity_ids` as keyword indexes for $O(1)$ fast metadata filtering.

### LLMs & API Gateways
- **Generation models**:
  - Primary: `google/gemini-2.5-flash-lite` (routed via Vercel AI Gateway).
  - Fallback: `meta/llama-3.1-70b-instruct` (NVIDIA NIM).
- **Dense Embedding model**: `nvidia/nv-embedqa-e5-v5` (1024 dimensions, 512 token max input limit, input-typed queries).
- **Re-ranking model**: `nvidia/llama-nemotron-rerank-1b-v2`.

---

## 2. Ingestion & Semantic Chunking Pipeline (`process_dataset.py`)

### Dataset Properties
- **Source Files**: 52 structured Markdown (`.md`) files covering college administration, departments, hostel, transport, admissions, sports, and placement.
- **Ingestion Scale**: **1692 total chunks** mapped and upserted into Qdrant Cloud.

### Chunking Parameters
Chunking is defined by semantic boundaries to ensure retrieval accuracy:
- `CHUNK_MIN = 60` (minimum characters per chunk).
- `CHUNK_MAX = 900` (hard limit, ~200-225 tokens) to fit inside the tight 512 token limit of the embedding model.
- `CHUNK_SOFT = 600` (soft target character count, ~150 tokens).
- `OVERLAP_MIN = 60` / `OVERLAP_MAX = 100` characters (overlap range to ensure continuity between chunks).
- `TABLE_MAX_SINGLE = 1800` characters (markdown tables are kept intact as a single block up to 1800 characters to prevent loss of relational row-column contexts).

---

## 3. PostgreSQL Database Schema

```sql
-- 1. Chat Sessions
CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY,
    user_id VARCHAR(100) DEFAULT 'anonymous',
    session_title VARCHAR(200) DEFAULT 'Chat Session',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Chat Messages
CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL, -- 'user' or 'assistant'
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    prompt_tokens INT DEFAULT 0,
    completion_tokens INT DEFAULT 0,
    citations JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Message Feedback
CREATE TABLE IF NOT EXISTS message_feedback (
    message_id UUID PRIMARY KEY REFERENCES chat_messages(id) ON DELETE CASCADE,
    session_id UUID NOT NULL,
    rating INT CHECK (rating IN (-1, 1)), -- 1 = thumbs-up, -1 = thumbs-down
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Feedback Self-Healing Correction Log
CREATE TABLE IF NOT EXISTS feedback_correction_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL,
    session_id UUID NOT NULL,
    user_query TEXT,
    original_answer TEXT,
    verdict VARCHAR(50), -- 'REAL_QA_MISMATCH' or 'USER_DISSATISFACTION_OR_FUN'
    reason TEXT,
    corrected_answer TEXT,
    cache_updated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. Semantic Cache
CREATE TABLE IF NOT EXISTS query_cache (
    query_hash VARCHAR(64) PRIMARY KEY, -- SHA-256 of normalized query text
    query_text TEXT NOT NULL,
    response_text TEXT NOT NULL,
    citations JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. End-to-End Query Handling Pipeline

When a client queries `POST /api/chat`, the request moves through these phases:

### Phase 1: Normalization & Spell Correction
1. The raw query is stripped and expanded for abbreviations (e.g., "cse admissions" $\rightarrow$ "computer science engineering admissions").
2. **Levenshtein Distance Spellcheck**: Corrects typos using a custom vocabulary built from the database tokens (`vocab.pkl`) combined with static MSAJCE keywords (e.g. `sholinganallur`, `kelambakkam`, `velachery`). It computes candidate edits within distance $\le 2$:
   ```python
   # Evaluates edit distance using python-Levenshtein
   distance = Levenshtein.distance(token, candidate)
   ```

### Phase 2: Multi-Turn Context Rewriting
If the current session contains previous messages:
1. The query is passed to `QueryRewriter`.
2. An LLM checks if the query references prior pronouns (e.g. "which bus goes there?", "who is the HOD?").
3. The LLM rewrites the query into an independent search string (e.g. "Who is the HOD of Computer Science Engineering at MSAJCE?").

### Phase 3: Classification & Metadata Filtering
The rewritten query is classified into a target category:
- Predicts category and confidence ($0.0 - 1.0$).
- If confidence exceeds the threshold (`CATEGORY_CONFIDENCE_THRESHOLD = 0.60`), a keyword filter is generated to restrict the subsequent vector search space.
- Special handling is injected for transport queries to override misclassification issues.

### Phase 4: Semantic Cache Lookup
The query is normalized (lowercased, spaces stripped, punctuation removed) and hashed using SHA-256:
```python
query_hash = hashlib.sha256(normalized_query.encode()).hexdigest()
```
- If the hash exists in `query_cache`, the response and citations are immediately returned, skipping retrieval and generation latency entirely (0ms execution time).

### Phase 5: Parallel Hybrid Retrieval
If cache misses, the system executes two search threads in parallel:
1. **Dense Semantic Search**: Generates a 1024-dimensional query embedding via `nv-embedqa-e5-v5` and searches Qdrant using Cosine Similarity, applying the category/metadata filters.
2. **Sparse Keyword Search**: Queries the local BM25 index built from the dataset vocabulary using the `rank-bm25` algorithm.

### Phase 6: Reciprocal Rank Fusion (RRF) & Re-ranking
The results from Dense and Sparse searches are combined. The RRF score for each document $d$ is calculated as:
$$score(d) = \sum_{m \in M} \frac{1}{RRF\_K + rank_m(d)}$$
Where $RRF\_K = 60$, and $rank_m(d)$ is the position of document $d$ in search result list $m$.
- The top 40 candidates are selected.
- These candidates are passed through the **Llama Nemotron Reranker** (`nvidia/llama-nemotron-rerank-1b-v2`), which outputs the final top 6 context blocks.

### Phase 7: Contextual Generation & Redaction
The top 6 context blocks are constructed into a prompt:
- Stricly grounded context instructions.
- Custom rendering formats (e.g. formatting schedules and lists into Markdown Tables).
- Post-generation redactions: Runs regex checks to strip leaked entity comment tags (`<!--ent_\d+-->`) and personal phone numbers (`+91XXXXXXXXXX`) to comply with strict security rules.

---

## 5. Thumbs-Down Feedback & Self-Healing Loop

If a user dislikes a generated answer (thumbs-down / rating `-1`):
1. **Immediate Purge**: The cache is evicted for the exact user query hash. Additionally, a fuzzy deletion is executed matching the first 40 characters of the query text to clear legacy cache versions.
2. **LLM Judge Audit**: The backend launches a background task that calls `meta/llama-3.1-8b-instruct` (NVIDIA NIM) as a Judge. The judge compares the user query, assistant response, and actual retrieved reference context.
3. **Verdict Classification**:
   - `USER_DISSATISFACTION_OR_FUN`: The response was factually correct, but the user is unhappy with the policy (e.g. fee is high, warden rules). No correction is made.
   - `REAL_QA_MISMATCH`: The response contradicts the context, contains incorrect figures, or missed critical facts.
4. **Self-Correction**: If classified as a `REAL_QA_MISMATCH`, a fresh hybrid retrieval is executed, a highly accurate corrected answer is synthesized by the LLM, and it is cached in `query_cache` to override any future queries. The audit log is recorded in `feedback_correction_log`.

---

## 6. RAGAS Offline Evaluator (`eval/ragas_eval.py`)

To monitor pipeline quality offline, a custom evaluator tests the live system against a benchmark dataset (`eval_dataset.json`):
- **Mechanism**: LLM-as-a-judge pipeline using `meta/llama-3.1-70b-instruct` as the judge and `nv-embedqa-e5-v5` for calculating answer embedding dimensions.
- **Metrics Tracked**:
  - **Faithfulness**: Measures whether all facts stated in the answer are strictly supported by the retrieved context.
  - **Answer Relevancy**: Measures how directly the generated response addresses the initial user question.
  - **Factual Correctness**: Evaluates accuracy against expected ground-truth answers.
- **Execution**: Can be run from anywhere (local laptop or CI/CD pipelines) against the live cloud Railway server:
  ```bash
  python eval/ragas_eval.py --api-url https://lorin-ai-production.up.railway.app
  ```
- **Output**: Logs aggregate metrics and per-category breakdowns to `eval/ragas_results_<timestamp>.json`.
