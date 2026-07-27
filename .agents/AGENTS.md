# Project Guidelines & Rules

## Model Selection
- Any models are allowed. No cost/budget constraints.


## RAG Architecture Rules
- Use **Qdrant Cloud** for vector storage (`college_knowledgebase` collection).
- Use **Hybrid Search** (Dense Vectors + BM25 Sparse Search).
- Use **LlamaParse** or visual parsers for PDF tables (fee structures, calendars).
- Use **Parent-Child Chunking** (150-250 token child chunks, 800-1200 parent context).
