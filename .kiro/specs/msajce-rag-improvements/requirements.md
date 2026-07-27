# Requirements Document

## Introduction

This document specifies the requirements for improving the MSAJCE (Mohamed Sathak A.J. College of Engineering) RAG chatbot pipeline. The current pipeline uses intent classification → cache lookup → dense vector search (Qdrant, top 25) → neural re-ranking (top 6) → LLM generation (Llama-3.1-8b). Ten prioritised improvements are defined here, ordered from the highest impact foundation (chunking quality) through to user feedback collection. All improvements must preserve the existing NVIDIA NIM API stack (Llama-3.1-8b, Nemotron-3-embed, Nemotron-Rerank), the Qdrant Cloud vector store, and the Supabase PostgreSQL backend.

---

## Glossary

- **Chunker**: The component in `process_dataset.py` responsible for splitting PDF text into storable, embeddable units.
- **Chunk**: A single text segment stored in Qdrant as one vector point, with associated payload metadata.
- **Retriever**: The component in `api_server.py` that queries Qdrant for candidate chunks given an embedding vector.
- **Re-ranker**: The NVIDIA `llama-nemotron-rerank-1b-v2` model call in `api_server.py` that scores and reorders candidate chunks.
- **Hybrid_Retriever**: A new retrieval component combining BM25 keyword search with dense vector search.
- **BM25_Index**: A keyword-based inverted index built over chunk text, used for sparse lexical retrieval.
- **RRF_Fusion**: Reciprocal Rank Fusion — a score-free rank combination algorithm that merges ranked lists from multiple retrievers.
- **Metadata_Filter**: A Qdrant payload filter applied before vector search to restrict candidate chunks by `category` or `section_title`.
- **Query_Rewriter**: An LLM-based component that rewrites a follow-up user message into a self-contained standalone question using conversation history (condense-question pattern).
- **Spell_Corrector**: A pre-processing component that maps misspelled query tokens to known vocabulary terms using edit-distance.
- **Eval_Harness**: A offline evaluation framework that scores pipeline outputs against a ground-truth Q&A dataset.
- **Faithfulness_Checker**: A conditional LLM component that verifies whether a generated answer is supported by the retrieved context, invoked only when re-ranker confidence is low.
- **Feedback_Store**: The Supabase table that records per-message thumbs-up / thumbs-down user signals.
- **Pipeline**: The full end-to-end request processing flow from user query to returned answer.
- **RERANK_SCORE_THRESHOLD**: The current minimum logit score (0.01) below which re-ranked chunks are discarded.
- **Session**: A `chat_sessions` record representing one continuous user conversation.
- **LLM**: Large Language Model — specifically `meta/llama-3.1-8b-instruct` via NVIDIA NIM, unless stated otherwise.
- **NIM**: NVIDIA Inference Microservices API endpoints used for embedding, re-ranking, and generation.
- **top_k**: The number of candidate chunks returned by the Retriever before re-ranking (currently 25).
- **top_n**: The number of chunks retained after re-ranking for context assembly (currently 6).

---

## Requirements

---

### Requirement 1: Chunking Audit and Semantic Boundary-Aware Re-Chunking

**User Story:** As a developer, I want the knowledge base to be chunked at clean semantic boundaries, so that retrieved chunks always contain complete, coherent information and the LLM is never given a fragment mid-sentence or mid-table.

#### Acceptance Criteria

1. THE Chunker SHALL split text exclusively at paragraph boundaries, section boundaries, or table row boundaries — never mid-sentence.
2. WHEN a detected section body contains a table (identified by two or more tab-separated or multi-space-aligned columns across three or more consecutive lines), THE Chunker SHALL keep the entire table in a single chunk unless the table exceeds 1 800 characters, in which case THE Chunker SHALL split only between complete rows and repeat the header row at the start of each continuation chunk.
3. THE Chunker SHALL target a chunk length between 400 and 900 characters of clean text, with a soft target of 600 characters.
4. WHEN a single paragraph exceeds 900 characters and cannot be split at a sentence boundary cleanly, THE Chunker SHALL split at the nearest sentence-ending punctuation (`.`, `?`, `!`) followed by whitespace that keeps both resulting chunks above 200 characters.
5. THE Chunker SHALL carry a 60–100 character overlap — taken from the final sentence of the preceding chunk — into the start of the following chunk, only when both chunks belong to the same section. The overlap length within that range requires no additional tuning guidance.
6. THE Chunker SHALL assign each chunk a `section_title` payload field set to the heading text of the enclosing section, or `"Overview"` if no heading is detected.
7. WHEN the `process_dataset.py` pipeline completes, THE Chunker SHALL log for each PDF: the number of chunks produced, the minimum chunk character length, the maximum chunk character length, and the mean chunk character length.
8. THE Chunker SHALL prevent the creation of chunks with fewer than 60 characters of non-whitespace text during the chunking process — by merging candidate short fragments with adjacent content before they become standalone chunks — and SHALL NOT produce nor upsert such short chunks to Qdrant.
9. THE Chunker SHALL preserve all existing payload fields (`source_file`, `category`, `section_title`, `page_number`, `parent_id`, `chunk_hash`) on every upserted point.
10. WHEN re-indexing is run on PDFs already present in Qdrant, THE Chunker SHALL upsert using the deterministic `chunk_hash`-derived point ID so that no duplicate vectors are created.

---

### Requirement 2: Metadata Filtering Before Vector Search

**User Story:** As a user, I want queries about a specific department or topic to retrieve only chunks from that category, so that irrelevant chunks from unrelated departments are not included in my answer.

#### Acceptance Criteria

1. THE Retriever SHALL accept an optional `category` filter parameter and, WHEN provided, SHALL pass it as a Qdrant payload filter restricting results to chunks whose `category` field exactly matches the supplied value.
2. WHEN the Query_Rewriter or intent classifier infers a department category with confidence, THE Pipeline SHALL propagate the inferred category to the Retriever as a metadata filter for that request.
3. THE Retriever SHALL maintain the existing `top_k` of 25 candidate chunks when a metadata filter is active; IF fewer than 10 filtered chunks exist in Qdrant for the given category, THEN THE Retriever SHALL fall back to an unfiltered search and SHALL log a warning containing the category name and the filtered hit count.
4. THE Pipeline SHALL expose the `category` values used in Qdrant as a discoverable list in `rag_config.py` so that new categories added during re-indexing are reflected without code changes to the Retriever.
5. WHEN no category can be inferred from the query, THE Retriever SHALL perform an unfiltered search identical to the current behaviour.
6. IF the metadata filter is applied and the filtered search returns zero results, THEN THE Retriever SHALL retry without the filter and SHALL include a `metadata_filter_fallback: true` field in the internal log entry for that request.

---

### Requirement 3: Hybrid Search with BM25 and RRF Fusion

**User Story:** As a user asking about exact identifiers like course codes, bus route numbers, or staff names, I want the system to find chunks containing those exact strings, so that dense-vector-only search does not miss lexically specific matches.

#### Acceptance Criteria

1. THE Hybrid_Retriever SHALL perform a BM25 keyword search and a dense vector search in parallel for every `college_query` request.
2. THE BM25_Index SHALL be built over the `text` field of all chunks currently stored in Qdrant at ingestion time and SHALL be persisted to a file so it can be loaded at API server startup without re-scanning Qdrant on every restart.
3. WHEN the BM25_Index is loaded at startup and the Qdrant collection has been modified since the index was last built (detected by comparing stored point counts), THE Hybrid_Retriever SHALL rebuild the BM25_Index and persist the updated version; this requirement is considered violated if either the rebuild or the persistence step fails.
4. THE BM25_Index SHALL retrieve up to `top_k` (25) candidates; THE Retriever SHALL retrieve up to `top_k` (25) dense candidates; THE RRF_Fusion step SHALL merge both lists into a single deduplicated ranked list of up to 40 candidates using the formula `score(d) = Σ 1 / (k + rank(d))` with `k = 60`.
5. THE Hybrid_Retriever SHALL pass the merged RRF list of up to 40 candidates to the existing Re-ranker, which SHALL then select the top_n (6) highest-scoring chunks for context assembly.
6. WHEN a query token exactly matches a string in a chunk (case-insensitive), THE BM25_Index SHALL assign that chunk a non-zero BM25 score, ensuring it appears in the BM25 candidate list.
7. THE BM25_Index SHALL support incremental updates: WHEN a new PDF is indexed, THE Chunker SHALL notify the BM25_Index to append the new chunk texts and rebuild the index file.
8. IF the BM25_Index file is missing or corrupted at server startup, THEN THE Hybrid_Retriever SHALL rebuild the index from Qdrant, log the rebuild event, and continue serving requests without interruption.
9. IF the BM25_Index lookup raises an exception during a live request (e.g., corrupted in-memory state, unexpected input), THEN THE Hybrid_Retriever SHALL proceed using only the dense-vector candidate list for that request, SHALL log a `WARN`-level message containing the exception details, and SHALL NOT return an error to the user.

---

### Requirement 4: Re-ranker Correctness Verification

**User Story:** As a developer, I want to confirm that the NVIDIA re-ranker is actually improving retrieval quality and not silently failing, so that I have confidence that re-ranking is a meaningful pipeline stage.

#### Acceptance Criteria

1. THE Pipeline SHALL log the raw logit scores returned by the Re-ranker for every request at `DEBUG` level, including the chunk index, the logit value, and whether the chunk passed `RERANK_SCORE_THRESHOLD`.
2. WHEN the Re-ranker API call fails (network error, timeout, or non-2xx response), THE Pipeline SHALL fall back to returning the top_n chunks ordered by their original dense-vector cosine similarity score and SHALL log a `WARN`-level message containing the exception details.
3. THE `RERANK_SCORE_THRESHOLD` SHALL be configurable in `rag_config.py`; changes to the value SHALL take effect on the next server startup without code changes elsewhere.
4. THE Pipeline SHALL expose a `/api/debug/rerank` endpoint that accepts `{"query": str, "passages": [str]}` and returns the raw re-ranker response including all logit scores, for manual diagnostic use.
5. WHEN all re-ranked logit scores for a request are below `RERANK_SCORE_THRESHOLD`, THE Pipeline SHALL widen the fallback pool by returning the top_n (6) candidates ranked by cosine similarity from the original top_k=25 candidate pool rather than returning an empty context, and SHALL log this event at `WARN` level. The fallback count matches top_n for consistency; tuning it lower is a configuration concern, not a spec change.
6. THE Pipeline SHALL record a `rerank_used: bool` field in the internal per-request trace so that the Eval_Harness can distinguish re-ranked from fallback responses.

---

### Requirement 5: Evaluation Dataset and Offline Metrics Harness

**User Story:** As a developer, I want a small evaluation dataset and an automated metrics script, so that I can measure the effect of each pipeline change with a repeatable, objective score before deploying it.

#### Acceptance Criteria

1. THE Eval_Harness SHALL include a ground-truth dataset of between 30 and 50 question–answer pairs drawn from the existing MSAJCE PDF documents, covering at least eight distinct `category` values present in the Qdrant collection.
2. THE ground-truth dataset SHALL be stored as a JSON file at `eval/eval_dataset.json` with the schema `[{"question": str, "expected_answer": str, "category": str, "source_file": str}]`.
3. THE Eval_Harness SHALL compute and report the following metrics for each evaluation run: Retrieval Recall@6 (whether the correct source chunk appears in the top 6 after re-ranking), Answer Exact-Match rate, and Answer F1 token-overlap score.
4. THE Eval_Harness SHALL write results to `eval/results_{timestamp}.json` containing per-question scores and aggregate averages.
5. WHEN the Eval_Harness is run via `python eval/run_eval.py`, THE Eval_Harness SHALL execute all questions against the live pipeline and print a summary table to stdout within 10 minutes for a 50-question dataset.
6. THE Eval_Harness SHALL support a `--pipeline-variant` flag so that two pipeline configurations (e.g., with and without hybrid search) can be compared by running the script twice and diffing the result files.
7. THE Eval_Harness SHALL support a `--bypass-cache` flag that, WHEN set, passes a dedicated `bypass_cache: true` field in the `ChatRequest` body so that the Pipeline skips the cache lookup for that request without modifying the query string or affecting retrieval semantics. THE API Server SHALL honour the `bypass_cache` field in `ChatRequest` by skipping the cache read step when it is `true`.
8. THE ground-truth dataset SHALL include at least five questions containing exact identifiers (course codes, bus route numbers, or staff names) to validate hybrid search performance.

---

### Requirement 6: LLM-Based Query Rewriting for Multi-Turn Conversations

**User Story:** As a user having a multi-turn conversation, I want the chatbot to understand my follow-up questions in context, so that short follow-up messages like "What about the fees?" are resolved into self-contained queries without me needing to repeat context.

#### Acceptance Criteria

1. THE Query_Rewriter SHALL rewrite a user message into a standalone question WHEN the current `session_id` has two or more prior assistant turns stored in `chat_messages` for that session.
2. THE Query_Rewriter SHALL use the LLM (Llama-3.1-8b) with a condense-question prompt pattern, providing the last four message turns (alternating user/assistant) and the current user message as input, and SHALL return a single rewritten standalone question string.
3. WHEN the Query_Rewriter determines that the current message is already self-contained (no coreference to prior turns), THE Query_Rewriter SHALL return the original message unmodified.
4. THE rewritten query — not the original user message — SHALL be passed to the keyword-expansion step, the BM25_Index search, and the dense vector embedding step.
5. THE Pipeline SHALL store the original user message in `chat_messages.content` and the rewritten query in `chat_messages.metadata` under the key `"rewritten_query"`, so both are auditable.
6. IF the Query_Rewriter LLM call fails or times out, THEN THE Pipeline SHALL fall back to using the original user message for retrieval and SHALL log a `WARN`-level message, without surfacing an error to the user.
7. THE Query_Rewriter SHALL NOT inject raw conversation history text directly into the retrieval embedding; it SHALL only produce the single rewritten query string that is then embedded normally.
8. THE `chat_messages` table SHALL be queried using the `session_id` field to retrieve prior turns; WHEN no `session_id` is supplied in the request, THE Pipeline SHALL skip Query_Rewriter and treat the message as a single-turn query.

---

### Requirement 7: Spell Correction Against Known Vocabulary

**User Story:** As a user who makes common spelling mistakes in department names, course names, or college-specific terms, I want my query to still retrieve correct results, so that typos do not cause retrieval failures.

#### Acceptance Criteria

1. THE Spell_Corrector SHALL maintain a known vocabulary list built from all unique tokens of length ≥ 4 extracted from the chunk `text` fields in Qdrant, plus a curated static list of MSAJCE-specific proper nouns (department names, course codes, key staff titles).
2. THE Spell_Corrector SHALL apply correction WHEN a query token has no exact match in the vocabulary AND the closest vocabulary match by Levenshtein edit distance is ≤ 2 edits and the candidate match appears at least 5 times in the vocabulary corpus.
3. THE Spell_Corrector SHALL operate on the user's raw input before intent classification and keyword expansion, producing a corrected query string that is passed to all downstream steps.
4. WHEN a token is corrected, THE Pipeline SHALL log the original token and the corrected token at `DEBUG` level.
5. THE Spell_Corrector SHALL NOT modify tokens that are numeric, URL-like, or already present in the vocabulary.
6. THE vocabulary list SHALL be co-located with the BM25_Index; WHEN a BM25_Index rebuild is triggered, THE Spell_Corrector vocabulary list SHALL be rebuilt as part of the same operation.
7. IF the vocabulary file is absent at startup, THEN THE Spell_Corrector SHALL build it from Qdrant and log the build event, then continue serving requests without interruption.
8. THE Spell_Corrector SHALL process a query in under 50 milliseconds for queries of up to 50 tokens, measured on the API server host.

---

### Requirement 8: Conditional Faithfulness Check on Low-Confidence Retrievals

**User Story:** As a user, I want the chatbot to avoid giving answers that are not supported by its source documents, so that I receive accurate information about MSAJCE without hallucinated details.

#### Acceptance Criteria

1. THE Faithfulness_Checker SHALL be invoked ONLY WHEN the highest logit score among the top_n re-ranked chunks is below a configurable threshold `FAITHFULNESS_TRIGGER_THRESHOLD` defined in `rag_config.py`, with a default value of 0.30.
2. WHEN invoked, THE Faithfulness_Checker SHALL send the generated answer and the assembled context to the LLM with a yes/no grounding prompt asking whether every factual claim in the answer is supported by the context.
3. IF the Faithfulness_Checker determines the answer is not grounded, THEN THE Pipeline SHALL replace the answer with the standard fallback message: "I don't have reliable information on that. Please contact the MSAJCE office at +91 99400 04500 or msajce.office@gmail.com."
4. THE Faithfulness_Checker SHALL NOT be invoked when the highest re-ranker logit score is ≥ `FAITHFULNESS_TRIGGER_THRESHOLD`; for high-confidence retrievals the generated answer SHALL be returned directly without an additional LLM call.
5. THE `FAITHFULNESS_TRIGGER_THRESHOLD` SHALL be configurable in `rag_config.py`; changes SHALL take effect on next server startup.
6. THE Pipeline SHALL record `faithfulness_check_invoked: bool` and `faithfulness_passed: bool | null` in the per-request internal trace for every request. WHEN the check was not invoked (high-confidence path), `faithfulness_check_invoked` SHALL be `false` and `faithfulness_passed` SHALL be `null` (not applicable). WHEN the check was invoked and the answer was grounded, `faithfulness_passed` SHALL be `true`. WHEN the check was invoked and the answer was not grounded, `faithfulness_passed` SHALL be `false`.
7. IF the Faithfulness_Checker LLM call fails or times out after 10 seconds, THEN THE Pipeline SHALL log a `WARN`-level message and return the originally generated answer unchanged; in this case `faithfulness_check_invoked` SHALL be `true` and `faithfulness_passed` SHALL be `null`.
8. THE Faithfulness_Checker SHALL add no latency to requests where the high-confidence path applies (logit ≥ `FAITHFULNESS_TRIGGER_THRESHOLD`).

---

### Requirement 9: User Feedback Collection (Thumbs Up / Down)

**User Story:** As a product owner, I want to collect user satisfaction signals on individual answers, so that I can identify which queries the pipeline handles poorly and prioritise improvements.

#### Acceptance Criteria

1. THE Feedback_Store SHALL be a Supabase table named `message_feedback` with columns: `id UUID PRIMARY KEY`, `message_id UUID NOT NULL UNIQUE REFERENCES chat_messages(id)`, `session_id UUID`, `rating SMALLINT CHECK (rating IN (-1, 1))`, `created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP`.
2. THE API Server SHALL expose a `POST /api/feedback` endpoint that accepts `{"message_id": str, "session_id": str, "rating": -1 | 1}` and inserts a row into `message_feedback`, returning HTTP 200 `{"status": "ok"}`.
3. WHEN a feedback submission is received with a `message_id` that does not exist in `chat_messages`, THE API Server SHALL return HTTP 404 with the body `{"error": "message not found"}`.
4. IF the `rating` field in a feedback submission is not exactly `-1` or `1`, THEN THE API Server SHALL return HTTP 422 with the body `{"error": "rating must be -1 or 1"}` before attempting any database insert.
4. THE React frontend SHALL render a thumbs-up and thumbs-down button below each assistant `MessageBubble` component only after the answer content has fully rendered (i.e., the complete message text is present in the DOM; for streaming mode, after the `event: done` SSE event is received).
5. WHEN the user clicks a feedback button, THE frontend SHALL call `POST /api/feedback`, disable both buttons for that message, and display a checkmark icon to confirm the rating was recorded.
6. THE frontend SHALL send feedback only once per message; after submission the buttons SHALL remain disabled for the lifetime of the session.
7. THE API Server SHALL accept duplicate feedback submissions for the same `message_id` gracefully using `ON CONFLICT (message_id) DO UPDATE SET rating = EXCLUDED.rating, created_at = CURRENT_TIMESTAMP` so that users can change their rating.
8. THE `message_feedback` table SHALL have an index on `message_id` for efficient lookup.

---

### Requirement 10: Lower-Priority Improvements — Query Decomposition, Streaming Responses, and Periodic Re-indexing

**User Story:** As a user with complex multi-part questions, I want the chatbot to handle them completely; as a user waiting for a long answer, I want to see text appear progressively; as a developer, I want the knowledge base to stay current as documents are updated.

#### Acceptance Criteria

**10a — Query Decomposition**

1. WHEN a user query is classified as containing two or more distinct information sub-questions (detected by the LLM intent classifier returning `intent: "compound_query"`), THE Pipeline SHALL decompose the query into sub-questions, retrieve and generate answers for each independently, and merge the answers into a single coherent response.
2. THE decomposition step SHALL produce at most 3 sub-questions per compound query; IF more than 3 sub-questions are identified, THE Pipeline SHALL process only the first 3 and append a note that the user may ask follow-up questions for remaining parts.

**10b — Streaming Responses**

3. THE API Server SHALL expose a `POST /api/chat/stream` endpoint that accepts the same `ChatRequest` body as `/api/chat` and returns a `text/event-stream` (SSE) response where each event contains a partial answer token chunk.
4. WHEN streaming is active, THE API Server SHALL send a final SSE event with `event: done` containing the full `citations` array and `tokenUsage` object as JSON, so the frontend can display sources after generation completes.
5. THE React frontend SHALL support an opt-in streaming mode: WHEN `streaming: true` is set in the `useCampusChat` hook configuration, THE hook SHALL connect to `/api/chat/stream` and progressively append tokens to the current assistant `MessageBubble`.

**10c — Periodic Re-indexing**

6. THE Chunker SHALL support a `--incremental` CLI flag: WHEN passed, THE Chunker SHALL compare each PDF's modification timestamp against the `updated_at` field in `scraped_documents` and re-process only PDFs that have changed since the last successful index run.
7. WHEN `--incremental` is used, THE Chunker SHALL delete existing Qdrant points whose `source_file` matches a changed PDF before upserting the new chunks, to prevent stale chunks from remaining in the index.
8. THE Chunker SHALL exit with a non-zero return code and a descriptive error message IF any required environment variable (`NVIDIA_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, `DATABASE_URL`) is absent at startup, so that misconfigured CI/CD pipelines fail loudly.
