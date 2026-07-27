-- Supabase Database Schema for College RAG Chatbot

-- 1. Scraped Documents Table (Stores raw scraped pages, PDFs, and processing status)
CREATE TABLE IF NOT EXISTS scraped_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(500) NOT NULL,
    source_url TEXT UNIQUE NOT NULL,
    content_type VARCHAR(50) DEFAULT 'webpage', -- 'webpage', 'pdf', 'docx'
    category VARCHAR(100) DEFAULT 'General',    -- 'Fees', 'Syllabus', 'Admission'
    raw_markdown TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    chunk_count INT DEFAULT 0,
    status VARCHAR(50) DEFAULT 'pending',       -- 'pending', 'indexed', 'failed'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Chat Sessions Table (User conversation sessions)
CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) DEFAULT 'anonymous',
    session_title VARCHAR(255) DEFAULT 'New Conversation',
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Chat Messages Table (Stores user queries, AI answers, citations, and costs)
CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL, -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    citations JSONB DEFAULT '[]'::jsonb, -- Array of document/chunk references
    prompt_tokens INT DEFAULT 0,
    completion_tokens INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Query Cache Table (FAQ Cache to save LLM tokens on repeated questions)
CREATE TABLE IF NOT EXISTS query_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_hash VARCHAR(64) UNIQUE NOT NULL, -- SHA-256 hash of normalized prompt
    query_text TEXT NOT NULL,
    response_text TEXT NOT NULL,
    citations JSONB DEFAULT '[]'::jsonb,
    hit_count INT DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for high-performance lookups
CREATE INDEX IF NOT EXISTS idx_scraped_url ON scraped_documents(source_url);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_query_cache_hash ON query_cache(query_hash);

-- ─────────────────────────────────────────────────────────────────────────────
-- RAG Pipeline Improvements — Schema Additions
-- ─────────────────────────────────────────────────────────────────────────────

-- 5. Add metadata column to chat_messages for storing per-request trace data
-- (Req 6.5, Req 8.6 — stores rewritten_query, faithfulness trace, etc.)
ALTER TABLE chat_messages 
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

-- 6. Message Feedback Table (Req 9.1 — thumbs up/down per assistant message)
-- IMPORTANT: message_id must be NOT NULL UNIQUE so ON CONFLICT (message_id) works
CREATE TABLE IF NOT EXISTS message_feedback (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL UNIQUE REFERENCES chat_messages(id) ON DELETE CASCADE,
    session_id UUID,
    rating     SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for efficient lookup (Req 9.8)
CREATE INDEX IF NOT EXISTS idx_message_feedback_message_id 
    ON message_feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_message_feedback_created_at 
    ON message_feedback(created_at DESC);
