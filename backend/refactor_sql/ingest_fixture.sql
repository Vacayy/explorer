-- Disposable ingest experiment only: deliberately separate from read projections.
CREATE TABLE ingest_blog_sources (
    url TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    blog_name TEXT NOT NULL
);
CREATE TABLE ingest_youtube_channels (
    channel_id TEXT PRIMARY KEY,
    title TEXT NOT NULL
);
CREATE TABLE ingest_documents (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    raw_content TEXT NOT NULL DEFAULT '',
    markdown TEXT NOT NULL,
    media_json JSONB,
    digest_status TEXT,
    content_hash TEXT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    projection_version BIGINT NOT NULL DEFAULT 1,
    projected_version BIGINT NOT NULL DEFAULT 0,
    UNIQUE (source_type, source_id)
);
CREATE TABLE ingest_enrichment_jobs (
    document_id BIGINT PRIMARY KEY REFERENCES ingest_documents(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'failed', 'done')),
    token UUID,
    worker_id TEXT,
    started_at TIMESTAMPTZ,
    CHECK ((status = 'running') = (token IS NOT NULL))
);
CREATE TABLE ingest_enrichments (
    document_id BIGINT PRIMARY KEY REFERENCES ingest_documents(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    summary TEXT,
    model TEXT NOT NULL
);
CREATE TABLE ingest_enrichment_history (
    document_id BIGINT NOT NULL REFERENCES ingest_documents(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    summary TEXT,
    model TEXT NOT NULL,
    PRIMARY KEY(document_id,revision)
);
CREATE TABLE ingest_youtube_jobs (
    document_id BIGINT PRIMARY KEY REFERENCES ingest_documents(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    transcript TEXT NOT NULL,
    status TEXT NOT NULL,
    token UUID,
    updated_at DOUBLE PRECISION NOT NULL,
    error TEXT
);
CREATE TABLE ingest_embeddings (
    document_id BIGINT PRIMARY KEY REFERENCES ingest_documents(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    embedding BYTEA NOT NULL CHECK (octet_length(embedding) = 1536)
);
