-- EloPhanto Phase 1: Knowledge & Memory schema
-- Reference file — the actual schema is created by core/database.py

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    heading_path TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    scope TEXT NOT NULL DEFAULT 'system',
    token_count INTEGER NOT NULL DEFAULT 0,
    file_updated_at TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    task_goal TEXT NOT NULL,
    task_summary TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'completed',
    tools_used TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    result TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    tokens_used INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    task_type TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    description TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

-- Gateway sessions
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    conversation_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    last_active TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(channel, user_id)
);

-- Document collections (RAG)
CREATE TABLE IF NOT EXISTS document_collections (
    collection_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    session_id TEXT,
    created_at TEXT NOT NULL,
    file_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0
);

-- Document files
CREATE TABLE IF NOT EXISTS document_files (
    file_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES document_collections(collection_id),
    filename TEXT NOT NULL,
    mime_type TEXT,
    size_bytes INTEGER,
    page_count INTEGER,
    local_path TEXT,
    content_hash TEXT,
    processed_at TEXT NOT NULL
);

-- Document chunks (for RAG retrieval)
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id TEXT NOT NULL REFERENCES document_collections(collection_id),
    file_id TEXT NOT NULL REFERENCES document_files(file_id),
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    page_number INTEGER,
    section_title TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
);

-- sqlite-vec virtual table for vector search (created only if extension is available)
-- CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
--     chunk_id INTEGER PRIMARY KEY,
--     embedding float[768]
-- );
--
-- CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_vec USING vec0(
--     chunk_id INTEGER PRIMARY KEY,
--     embedding float[768]
-- );
