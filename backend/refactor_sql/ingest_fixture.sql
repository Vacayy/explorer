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
    fetched_at TEXT,
    raw_content TEXT NOT NULL DEFAULT '',
    markdown TEXT NOT NULL,
    media_json JSONB,
    digest_status TEXT,
    content_hash TEXT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    projection_version BIGINT NOT NULL DEFAULT 1,
    projected_version BIGINT NOT NULL DEFAULT 0,
    enrichment_dirty BOOLEAN NOT NULL DEFAULT FALSE,
    embedding_dirty BOOLEAN NOT NULL DEFAULT FALSE,
    links_dirty BOOLEAN NOT NULL DEFAULT FALSE,
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
    model TEXT
);
CREATE TABLE ingest_legacy_video_archive (
    document_id BIGINT PRIMARY KEY REFERENCES ingest_documents(id) ON DELETE CASCADE,
    document JSONB NOT NULL,
    enrichments JSONB NOT NULL,
    job JSONB
);
CREATE TABLE ingest_enrichment_history (
    document_id BIGINT NOT NULL REFERENCES ingest_documents(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    summary TEXT,
    model TEXT,
    PRIMARY KEY(document_id,revision)
);
CREATE TABLE ingest_youtube_jobs (
    document_id BIGINT PRIMARY KEY REFERENCES ingest_documents(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    transcript TEXT,
    status TEXT NOT NULL,
    token UUID,
    updated_at DOUBLE PRECISION NOT NULL,
    error TEXT
);
CREATE TABLE ingest_embeddings (
    document_id BIGINT PRIMARY KEY REFERENCES ingest_documents(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    embedding BYTEA NOT NULL CHECK (octet_length(embedding) = 1536),
    model TEXT NOT NULL
);
CREATE TABLE ingest_entity_links (
    document_id BIGINT NOT NULL REFERENCES ingest_documents(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    position INTEGER NOT NULL,
    entity_id BIGINT NOT NULL,
    link_type TEXT NOT NULL,
    confidence DOUBLE PRECISION,
    PRIMARY KEY(document_id,revision,position),
    UNIQUE(document_id,revision,entity_id,link_type)
);
CREATE TABLE ingest_graph_state (singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(singleton));
CREATE TABLE ingest_graph_entities (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type TEXT NOT NULL, name TEXT NOT NULL, aliases TEXT, status TEXT,
    UNIQUE(type,name)
);
CREATE TABLE ingest_graph_keywords (
    entity_id BIGINT NOT NULL, keyword TEXT NOT NULL, status TEXT,
    UNIQUE(entity_id,keyword)
);
CREATE TABLE ingest_graph_relations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    src_id BIGINT NOT NULL, dst_id BIGINT NOT NULL, rel_type TEXT NOT NULL,
    epistemic_type TEXT, confidence DOUBLE PRECISION, source_doc_id BIGINT, valid_from TEXT,
    source_ordinal BIGINT,
    UNIQUE(src_id,dst_id,rel_type,valid_from)
);
