-- Experimental sector-map data only; detail, Peer and historical generations
-- are deliberately not represented by this schema.
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
    sector TEXT NOT NULL
);

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
