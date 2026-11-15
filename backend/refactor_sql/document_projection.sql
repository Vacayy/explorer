-- Synthetic read model for the isolated refactor experiment. Not a migration.
CREATE TABLE document_projection (
    id BIGINT PRIMARY KEY,
    source_type TEXT NOT NULL,
    published_at TEXT,
    detail_document JSONB NOT NULL,
    feed_visible BOOLEAN NOT NULL DEFAULT TRUE,
    source_groups TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    CHECK (jsonb_typeof(detail_document) = 'object'),
    CHECK ((detail_document->>'id') IS NOT DISTINCT FROM id::text)
);
-- Existing SQLite feed can produce multiple rows for one document when it has
-- multiple saved enrichments, even though total counts distinct source documents.
CREATE TABLE document_list_projection (
    ordinal BIGINT PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES document_projection(id),
    list_document JSONB NOT NULL,
    CHECK (jsonb_typeof(list_document) = 'object'),
    CHECK ((list_document->>'id') IS NOT DISTINCT FROM document_id::text)
);
CREATE INDEX document_projection_order ON document_projection (published_at DESC NULLS LAST, id);
CREATE INDEX document_list_projection_document ON document_list_projection (document_id);

CREATE TABLE snapshot_metadata (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    snapshot_at TEXT NOT NULL,
    document_count BIGINT NOT NULL,
    list_row_count BIGINT NOT NULL
);

-- Private intermediate source archive. JSON preserves SQLite's field names,
-- nulls and duplicate rows; it is not the final normalized PostgreSQL schema.
CREATE TABLE legacy_snapshot_tables (
    table_name TEXT PRIMARY KEY,
    columns JSONB NOT NULL,
    schema_sql TEXT NOT NULL,
    row_count BIGINT NOT NULL
);
CREATE TABLE legacy_snapshot_rows (
    table_name TEXT NOT NULL REFERENCES legacy_snapshot_tables(table_name),
    row_ordinal BIGINT NOT NULL,
    row_data JSONB NOT NULL,
    PRIMARY KEY (table_name, row_ordinal)
);
