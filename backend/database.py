import sqlite3
from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS companies (
        corp_code    TEXT PRIMARY KEY,
        corp_name    TEXT NOT NULL,
        stock_code   TEXT,
        market       TEXT,
        sector       TEXT,
        updated_at   TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_companies_stock_code ON companies(stock_code);
    CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(corp_name);

    CREATE TABLE IF NOT EXISTS financial_statements (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        corp_code       TEXT NOT NULL,
        bsns_year       INTEGER NOT NULL,
        reprt_code      TEXT NOT NULL,
        fs_div          TEXT NOT NULL,
        sj_div          TEXT NOT NULL,
        account_nm      TEXT NOT NULL,
        thstrm_amount   TEXT,
        frmtrm_amount   TEXT,
        bfefrmtrm_amount TEXT,
        ord             INTEGER,
        fetched_at      TEXT DEFAULT (datetime('now')),
        UNIQUE(corp_code, bsns_year, reprt_code, fs_div, sj_div, account_nm)
    );

    CREATE TABLE IF NOT EXISTS disclosures (
        rcp_no       TEXT PRIMARY KEY,
        corp_code    TEXT NOT NULL,
        corp_name    TEXT,
        report_nm    TEXT,
        rcept_dt     TEXT,
        flr_nm       TEXT,
        rm           TEXT,
        kind         TEXT,
        dart_url     TEXT,
        fetched_at   TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_disclosures_corp ON disclosures(corp_code, rcept_dt);

    CREATE TABLE IF NOT EXISTS business_segments (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        corp_code       TEXT NOT NULL,
        bsns_year       INTEGER NOT NULL,
        reprt_code      TEXT NOT NULL DEFAULT '11011',
        segment_type    TEXT NOT NULL,
        segment_name    TEXT NOT NULL,
        revenue         REAL,
        ratio           REAL,
        fetched_at      TEXT DEFAULT (datetime('now')),
        UNIQUE(corp_code, bsns_year, reprt_code, segment_type, segment_name)
    );

    CREATE TABLE IF NOT EXISTS ir_notes (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        corp_code    TEXT NOT NULL,
        title        TEXT NOT NULL,
        content      TEXT,
        memo_type    TEXT DEFAULT 'general',
        note_date    TEXT NOT NULL,
        created_at   TEXT DEFAULT (datetime('now')),
        updated_at   TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_ir_notes_corp ON ir_notes(corp_code, note_date);

    CREATE TABLE IF NOT EXISTS stock_prices (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code   TEXT NOT NULL,
        trade_date   TEXT NOT NULL,
        open         INTEGER,
        high         INTEGER,
        low          INTEGER,
        close        INTEGER,
        volume       INTEGER,
        market_cap   INTEGER,
        shares       INTEGER,
        fetched_at   TEXT DEFAULT (datetime('now')),
        UNIQUE(stock_code, trade_date)
    );
    CREATE INDEX IF NOT EXISTS idx_stock_prices_ticker_date ON stock_prices(stock_code, trade_date);

    CREATE TABLE IF NOT EXISTS fundamentals (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code   TEXT NOT NULL,
        trade_date   TEXT NOT NULL,
        bps          REAL,
        per          REAL,
        pbr          REAL,
        eps          REAL,
        div_yield    REAL,
        dps          REAL,
        fetched_at   TEXT DEFAULT (datetime('now')),
        UNIQUE(stock_code, trade_date)
    );
    CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker_date ON fundamentals(stock_code, trade_date);

    CREATE TABLE IF NOT EXISTS cache_meta (
        cache_key    TEXT PRIMARY KEY,
        fetched_at   TEXT DEFAULT (datetime('now')),
        expires_at   TEXT
    );

    CREATE TABLE IF NOT EXISTS industry_groups (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT NOT NULL UNIQUE,
        description  TEXT,
        created_at   TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS industry_members (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id     INTEGER NOT NULL REFERENCES industry_groups(id) ON DELETE CASCADE,
        stock_code   TEXT NOT NULL,
        category     TEXT NOT NULL,
        sort_order   INTEGER DEFAULT 0,
        created_at   TEXT DEFAULT (datetime('now')),
        UNIQUE(group_id, stock_code)
    );
    CREATE INDEX IF NOT EXISTS idx_industry_members_group ON industry_members(group_id, category);

    CREATE TABLE IF NOT EXISTS watchlist (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code   TEXT NOT NULL UNIQUE,
        corp_code    TEXT NOT NULL,
        corp_name    TEXT NOT NULL,
        conviction   INTEGER DEFAULT 3 CHECK(conviction BETWEEN 1 AND 5),
        target_price INTEGER,
        thesis       TEXT,
        created_at   TEXT DEFAULT (datetime('now')),
        updated_at   TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS catalysts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code   TEXT,
        corp_code    TEXT,
        event_type   TEXT NOT NULL,
        event_date   TEXT NOT NULL,
        title        TEXT NOT NULL,
        description  TEXT,
        created_at   TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS consensus (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code    TEXT NOT NULL,
        data_source   TEXT NOT NULL DEFAULT 'fnguide',
        fiscal_year   TEXT NOT NULL,
        revenue_est   REAL,
        op_profit_est REAL,
        net_income_est REAL,
        eps_est       REAL,
        bps_est       REAL,
        per_est       REAL,
        target_price  REAL,
        analyst_count INTEGER,
        opinion       TEXT,
        fetched_at    TEXT DEFAULT (datetime('now')),
        UNIQUE(stock_code, data_source, fiscal_year)
    );

    CREATE TABLE IF NOT EXISTS telegram_channels (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_name TEXT NOT NULL UNIQUE,
        display_name TEXT,
        is_active    INTEGER DEFAULT 1,
        last_fetched_at TEXT,
        added_at     TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS telegram_messages (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_name TEXT NOT NULL,
        message_id   TEXT,
        content      TEXT,
        date         TEXT,
        link         TEXT,
        fetched_at   TEXT DEFAULT (datetime('now')),
        UNIQUE(channel_name, message_id)
    );

    CREATE TABLE IF NOT EXISTS blog_sources (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        url          TEXT NOT NULL UNIQUE,
        platform     TEXT NOT NULL,
        blog_name    TEXT,
        is_active    INTEGER DEFAULT 1,
        last_fetched_at TEXT,
        added_at     TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS blog_posts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id    INTEGER NOT NULL,
        title        TEXT NOT NULL,
        summary      TEXT,
        content      TEXT,
        author       TEXT,
        url          TEXT,
        published_at TEXT,
        fetched_at   TEXT DEFAULT (datetime('now')),
        UNIQUE(source_id, url)
    );

    CREATE TABLE IF NOT EXISTS blog_post_tags (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id      INTEGER NOT NULL,
        tag_type     TEXT NOT NULL,
        tag_value    TEXT NOT NULL,
        UNIQUE(post_id, tag_type, tag_value)
    );
    CREATE INDEX IF NOT EXISTS idx_blog_post_tags ON blog_post_tags(tag_type, tag_value);
    """)

    conn.commit()

    for migration in [
        "ALTER TABLE ir_notes ADD COLUMN memo_type TEXT DEFAULT 'general'",
        "ALTER TABLE telegram_channels ADD COLUMN is_active INTEGER DEFAULT 1",
        "ALTER TABLE telegram_channels ADD COLUMN last_fetched_at TEXT",
        "ALTER TABLE blog_sources ADD COLUMN is_active INTEGER DEFAULT 1",
        "ALTER TABLE blog_sources ADD COLUMN last_fetched_at TEXT",
        "ALTER TABLE blog_posts ADD COLUMN author TEXT",
    ]:
        try:
            conn.execute(migration)
            conn.commit()
        except Exception:
            pass

    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized.")
