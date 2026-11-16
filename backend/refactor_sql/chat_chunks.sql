-- One document generation's exact source chunks and 384-dimensional vectors.
-- This is experimental fixture storage, not a production migration.
CREATE TABLE chat_chunk_projection (
    id BIGINT PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES document_projection(id),
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    prefix TEXT,
    content_hash TEXT,
    embedding BYTEA NOT NULL CHECK (octet_length(embedding) = 1536),
    UNIQUE (document_id, chunk_index)
);
CREATE INDEX chat_chunk_projection_doc ON chat_chunk_projection (document_id, chunk_index);
CREATE TABLE chat_chunk_metadata (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    generation_id UUID NOT NULL,
    chunk_count BIGINT NOT NULL,
    document_count BIGINT NOT NULL,
    stale_chunk_count BIGINT NOT NULL,
    complete BOOLEAN NOT NULL
);
