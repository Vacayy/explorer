-- Disposable ingest experiment only: deliberately separate from read projections.
CREATE TABLE ingest_documents (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    markdown TEXT NOT NULL,
    media_json JSONB,
    content_hash TEXT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    UNIQUE (source_type, source_id)
);
CREATE TABLE ingest_enrichments (
    document_id BIGINT PRIMARY KEY REFERENCES ingest_documents(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    summary TEXT,
    model TEXT NOT NULL
);
