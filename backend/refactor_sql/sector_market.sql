-- Experimental sector-map data only; detail, Peer and historical generations
-- are deliberately not represented by this schema.
CREATE TABLE sector_market_metadata (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    generation_id UUID NOT NULL,
    linked_document_generation BOOLEAN NOT NULL
);
CREATE TABLE sector_market_prices (
    id BIGINT PRIMARY KEY,
    stock_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open BIGINT, high BIGINT, low BIGINT, close BIGINT,
    volume BIGINT, market_cap BIGINT, shares BIGINT,
    fetched_at TEXT,
    UNIQUE (stock_code, trade_date)
);
CREATE INDEX sector_market_snapshot_idx
    ON sector_market_prices (stock_code COLLATE "C", trade_date DESC)
    WHERE close IS NOT NULL;

-- This is a derived snapshot, not a replacement for the source classification,
-- entity, and override tables used by other industry screens.
CREATE TABLE sector_market_membership (
    stock_code TEXT PRIMARY KEY,
    sector TEXT NOT NULL,
    ordinal BIGINT NOT NULL UNIQUE
);

CREATE TABLE sector_market_companies (
    ordinal BIGINT PRIMARY KEY, stock_code TEXT NOT NULL, corp_name TEXT
);
CREATE INDEX sector_market_companies_code ON sector_market_companies(stock_code);

CREATE TABLE sector_market_groups (sector TEXT PRIMARY KEY);
CREATE TABLE sector_market_peer_links (
    sector TEXT NOT NULL,
    peer_group_id TEXT NOT NULL,
    sort INTEGER NOT NULL,
    partial INTEGER NOT NULL,
    note TEXT,
    source TEXT NOT NULL,
    PRIMARY KEY (sector, peer_group_id)
);

CREATE TABLE sector_market_benchmarks (
    sector TEXT PRIMARY KEY, ticker TEXT, name TEXT, tracks TEXT, note TEXT
);
CREATE TABLE sector_market_benchmark_prices (
    ticker TEXT NOT NULL, trade_date TEXT NOT NULL, close DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (ticker, trade_date)
);
CREATE TABLE sector_market_us_metadata (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    generation_id UUID NOT NULL,
    classifications BIGINT NOT NULL
);
CREATE TABLE sector_market_us_classifications (
    ticker TEXT PRIMARY KEY, sector TEXT, industry TEXT, fetched_at TEXT
);
CREATE TABLE sector_market_index (
    sector TEXT NOT NULL, trade_date TEXT NOT NULL, value DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (sector, trade_date)
);

-- Optional captured Peer bundle, committed with the market snapshot. This
-- does not assert the source SQLite database and file were captured atomically.
CREATE TABLE sector_market_peer_runtime (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    payload JSONB NOT NULL
);

CREATE TABLE sector_market_sector_names (sector_name TEXT, group_name TEXT NOT NULL);
CREATE TABLE sector_market_themes (group_name TEXT, themes_json TEXT);
CREATE TABLE sector_market_narratives (
    ordinal BIGINT PRIMARY KEY, id BIGINT NOT NULL, topic TEXT, title TEXT,
    core_question TEXT, doc_count INTEGER, created_at TEXT
);
CREATE TABLE sector_market_entities (id BIGINT PRIMARY KEY, type TEXT, name TEXT, status TEXT);
CREATE INDEX sector_market_entity_name ON sector_market_entities(type, name);
CREATE TABLE sector_market_company_entities (entity_id BIGINT NOT NULL, stock_code TEXT NOT NULL);
CREATE INDEX sector_market_company_entity_code ON sector_market_company_entities(stock_code);
CREATE TABLE sector_market_documents (id BIGINT PRIMARY KEY, source_type TEXT, source_id TEXT, title TEXT, published_at TEXT);
CREATE TABLE sector_market_document_links (id BIGINT PRIMARY KEY, doc_id BIGINT, entity_id BIGINT, link_type TEXT);
CREATE INDEX sector_market_document_link_entity ON sector_market_document_links(entity_id, id);
-- The original query has no ORDER BY. Preserve its observed scan policy so
-- equal-time document ties keep their existing order for this snapshot.
CREATE TABLE sector_market_doc_scan (id_count INTEGER PRIMARY KEY, document_first BOOLEAN NOT NULL);
CREATE TABLE sector_market_trade_follow (
    ordinal BIGINT PRIMARY KEY, hs_code TEXT, item_name TEXT, group_label TEXT, active INTEGER
);
CREATE TABLE sector_market_trade_stats (id BIGINT PRIMARY KEY, hs_code TEXT, period TEXT, export_usd DOUBLE PRECISION);
CREATE INDEX sector_market_trade_stats_lookup ON sector_market_trade_stats(hs_code, period);
CREATE TABLE sector_market_taiwan_revenue (code TEXT, ym TEXT, yoy_pct DOUBLE PRECISION);
CREATE INDEX sector_market_taiwan_revenue_lookup ON sector_market_taiwan_revenue(ym, code);
CREATE TABLE sector_market_season_themes (id BIGINT PRIMARY KEY, season TEXT, sector TEXT, verdict TEXT, body_json TEXT);
CREATE TABLE sector_market_overviews (
    sector TEXT PRIMARY KEY, question TEXT, bullets_json TEXT, narrative_ids TEXT, model TEXT, generated_at TEXT
);
