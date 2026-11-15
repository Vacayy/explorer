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
    source_observed_at TIMESTAMPTZ NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
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

-- Each source filter may use a different SQLite index for tied timestamps.
-- Preserve the order observed for that filter, including duplicate enrichments.
CREATE TABLE document_filter_order (
    filter_key TEXT NOT NULL,
    position BIGINT NOT NULL,
    list_ordinal BIGINT NOT NULL REFERENCES document_list_projection(ordinal),
    PRIMARY KEY (filter_key, position),
    UNIQUE (filter_key, list_ordinal)
);
CREATE INDEX legacy_snapshot_rows_by_id ON legacy_snapshot_rows (table_name, (row_data->>'id'));
CREATE INDEX legacy_snapshot_rows_by_doc_id ON legacy_snapshot_rows (table_name, (row_data->>'doc_id'));

-- SQLite detail does not specify ORDER BY for entity links. Preserve its
-- observed per-document order separately from the raw rows and response cache.
CREATE TABLE document_entity_order (
    document_id BIGINT NOT NULL REFERENCES document_projection(id),
    position BIGINT NOT NULL,
    entity_id BIGINT NOT NULL,
    link_type TEXT NOT NULL,
    confidence DOUBLE PRECISION,
    occurrence BIGINT NOT NULL,
    PRIMARY KEY (document_id, position)
);

-- Private source-lane projection for the existing timeline API. System events
-- and channel directory are not represented by this table.
CREATE TABLE timeline_source_projection (
    id TEXT PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES document_projection(id),
    occurred_at TIMESTAMPTZ NOT NULL,
    sort_millis BIGINT NOT NULL,
    channel TEXT NOT NULL,
    platform TEXT NOT NULL,
    topic_names TEXT[] NOT NULL,
    time_label TEXT NOT NULL,
    preview TEXT NOT NULL,
    document JSONB NOT NULL
);
CREATE INDEX timeline_source_order ON timeline_source_projection (sort_millis DESC, id DESC);
CREATE INDEX timeline_source_channel ON timeline_source_projection (channel, sort_millis DESC, id DESC);

CREATE TABLE timeline_system_projection (
    id TEXT PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    sort_millis BIGINT NOT NULL,
    channel TEXT NOT NULL,
    topic TEXT,
    name TEXT NOT NULL,
    preview TEXT NOT NULL,
    item JSONB NOT NULL
);
CREATE INDEX timeline_system_order ON timeline_system_projection (sort_millis DESC, id DESC);
