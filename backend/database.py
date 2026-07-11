import sqlite3
from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # timeout: cron 수집(쓰기)과 API 요청이 겹칠 때 'database is locked' 대신 대기
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
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

    -- ============================================================
    -- 그래프 척추 (Phase 1 ETL spine) — 신규 단일 진실원천.
    -- 기존 테이블/라우터와 독립. docs/ontology.md, docs/specs/phase1-etl-spine.md 참조.
    -- ============================================================

    -- 노드: company/institution/product/theme/sector/event/person/policy/...
    CREATE TABLE IF NOT EXISTS entities (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        type         TEXT NOT NULL,
        name         TEXT NOT NULL,
        aliases      TEXT,
        meta_json    TEXT,
        status       TEXT NOT NULL DEFAULT 'active',  -- active | proposed
        created_at   TEXT DEFAULT (datetime('now')),
        UNIQUE(type, name)
    );
    CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);

    -- 엣지: 단방향 저장. epistemic_type으로 사실/가설 분리(비타협 원칙).
    CREATE TABLE IF NOT EXISTS entity_relations (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        src_id         INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        dst_id         INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        rel_type       TEXT NOT NULL,
        epistemic_type TEXT NOT NULL DEFAULT 'fact',  -- fact | hypothesis
        confidence     REAL,
        source_doc_id  INTEGER REFERENCES raw_documents(id) ON DELETE SET NULL,
        valid_from     TEXT,
        valid_to       TEXT,
        created_at     TEXT DEFAULT (datetime('now')),
        UNIQUE(src_id, dst_id, rel_type, valid_from)
    );
    CREATE INDEX IF NOT EXISTS idx_entity_relations_src ON entity_relations(src_id, rel_type);
    CREATE INDEX IF NOT EXISTS idx_entity_relations_dst ON entity_relations(dst_id, rel_type);

    -- 시계열: 도메인 원본 테이블의 핵심 라인 투영 (2계층 저장).
    CREATE TABLE IF NOT EXISTS observations (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_id    INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        date         TEXT NOT NULL,
        metric       TEXT NOT NULL,
        value        REAL,
        unit         TEXT,
        source       TEXT,
        UNIQUE(entity_id, date, metric, source)
    );
    CREATE INDEX IF NOT EXISTS idx_observations_entity ON observations(entity_id, metric, date);

    -- 문서: 모든 소스의 정규화 결과 통합. content_hash로 멱등성.
    CREATE TABLE IF NOT EXISTS raw_documents (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        source_type  TEXT NOT NULL,
        source_id    TEXT NOT NULL,
        title        TEXT,
        url          TEXT,
        published_at TEXT,
        fetched_at   TEXT DEFAULT (datetime('now')),
        raw_content  TEXT,
        markdown     TEXT,
        content_hash TEXT,
        UNIQUE(source_type, source_id)
    );
    CREATE INDEX IF NOT EXISTS idx_raw_documents_hash ON raw_documents(content_hash);

    -- LLM 강화 결과 (문서당 1건, content_hash로 캐시).
    CREATE TABLE IF NOT EXISTS enrichments (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id       INTEGER NOT NULL REFERENCES raw_documents(id) ON DELETE CASCADE,
        summary      TEXT,
        sentiment    TEXT,
        model        TEXT,
        content_hash TEXT,
        enriched_at  TEXT DEFAULT (datetime('now')),
        UNIQUE(doc_id, content_hash)
    );

    -- 문서↔엔티티 링크 (기존 blog_post_tags의 일반화).
    CREATE TABLE IF NOT EXISTS entity_links (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id       INTEGER NOT NULL REFERENCES raw_documents(id) ON DELETE CASCADE,
        entity_id    INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        link_type    TEXT NOT NULL DEFAULT 'mention',  -- mention | stock | industry | topic
        confidence   REAL,
        UNIQUE(doc_id, entity_id, link_type)
    );
    CREATE INDEX IF NOT EXISTS idx_entity_links_entity ON entity_links(entity_id, link_type);

    -- 파생 신호 (docs/specs/signals-spine.md). 산출값(payload)과 LLM 해석을 분리 저장.
    CREATE TABLE IF NOT EXISTS signals (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_type          TEXT NOT NULL,     -- mention_surge | export_change | high_52w
        entity_id            INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        date                 TEXT NOT NULL,     -- 신호 산출 기준일
        payload_json         TEXT,              -- 산출값 (카운트, 키워드, 근거 doc_ids 등)
        interpretation       TEXT,              -- LLM 해석 (epistemic: hypothesis)
        interpretation_model TEXT,
        created_at           TEXT DEFAULT (datetime('now')),
        UNIQUE(signal_type, entity_id, date)
    );
    CREATE INDEX IF NOT EXISTS idx_signals_type_date ON signals(signal_type, date);

    -- 기업활동 (Corporate Actions) — DART 전 시장 공시에서 키워드 분류 + 시총 필터
    CREATE TABLE IF NOT EXISTS corporate_actions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        rcp_no       TEXT NOT NULL UNIQUE,   -- DART 접수번호 (멱등)
        corp_code    TEXT,
        corp_name    TEXT,
        stock_code   TEXT,
        market       TEXT,                   -- Y=유가 K=코스닥
        action_type  TEXT NOT NULL,          -- 유상증자|무상증자|공개매수|주식분할|합병|회사분할|감자
        report_nm    TEXT,
        rcept_dt     TEXT,                   -- YYYYMMDD
        market_cap   INTEGER,                -- 스캔 시점 시총 (원)
        created_at   TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_corporate_actions_dt ON corporate_actions(rcept_dt, action_type);

    -- 종목별 사용자 정의 매칭 키워드 (결정적 매칭 — LLM 별칭 인식의 보완)
    CREATE TABLE IF NOT EXISTS entity_keywords (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_id    INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        keyword      TEXT NOT NULL,
        created_at   TEXT DEFAULT (datetime('now')),
        UNIQUE(entity_id, keyword)
    );

    -- 종목별 언급 다이제스트 (1D / 롤링 7D) — 내러티브의 시계열 아카이브
    CREATE TABLE IF NOT EXISTS entity_digests (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_id    INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        period       TEXT NOT NULL,          -- 1d | 7d (7d는 롤링, period_start=기준일)
        period_start TEXT NOT NULL,          -- KST 날짜 (YYYY-MM-DD)
        digest       TEXT,                   -- 요약 본문 (마크다운)
        insights     TEXT,                   -- 이전 요약 대비 '새로운 시각' (없으면 NULL)
        doc_count    INTEGER,
        doc_ids_hash TEXT,                   -- 재생성 가드 (문서 집합 변경 시에만 재생성)
        model        TEXT,
        created_at   TEXT DEFAULT (datetime('now')),
        UNIQUE(entity_id, period, period_start)
    );
    CREATE INDEX IF NOT EXISTS idx_entity_digests ON entity_digests(entity_id, period, period_start);

    -- 대화 영속화 (P2-0, docs/specs/product-v3.md §2) — 질문·후속질문 = 사용자 의도 데이터
    -- 에코챔버 방지: chat_messages는 검색 인덱스(doc_fts/doc_vec) 대상이 아니다
    CREATE TABLE IF NOT EXISTS conversations (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        title            TEXT,                   -- 첫 질문 앞 60자 (자동)
        anchor_entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
        channel          TEXT NOT NULL DEFAULT 'web',  -- web | telegram
        created_at       TEXT DEFAULT (datetime('now')),
        updated_at       TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS chat_messages (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role            TEXT NOT NULL,           -- user | assistant
        content         TEXT NOT NULL,
        citations_json  TEXT,                    -- assistant: 출처 인용
        gaps_json       TEXT,                    -- assistant: 갭 분석
        model           TEXT,                    -- assistant: epistemic 표시
        created_at      TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_chat_messages_conv ON chat_messages(conversation_id, id);
    -- 질문 메시지 → 종목 링크 (결정적 매칭, LLM 0토큰) — "내가 물어본 것들"의 근간
    CREATE TABLE IF NOT EXISTS chat_entity_links (
        message_id INTEGER NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
        entity_id  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        link_type  TEXT,
        UNIQUE(message_id, entity_id)
    );

    -- 소스(채널/블로그) 관점 프로필 — 열람 시 게으른 생성 (docs/specs/source-dossier.md)
    CREATE TABLE IF NOT EXISTS source_digests (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        kind         TEXT NOT NULL,          -- telegram | blog
        key          TEXT NOT NULL,          -- channel_name | blog url
        digest       TEXT,                   -- 관점·관심사 프로필 (마크다운)
        insights     TEXT,                   -- 지난 프로필 이후 새 관심사·시각 변화 (없으면 NULL)
        doc_count    INTEGER,
        doc_ids_hash TEXT,                   -- 재생성 가드 (문서 집합 변경 시에만 재생성)
        model        TEXT,
        created_at   TEXT DEFAULT (datetime('now')),
        UNIQUE(kind, key)
    );

    -- 유·무상증자 상세 (Pro 뷰) — 결정 공시 원문에서 구조화 추출
    CREATE TABLE IF NOT EXISTS capital_raise_details (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        rcp_no         TEXT NOT NULL UNIQUE,   -- corporate_actions.rcp_no
        stock_code     TEXT,
        corp_name      TEXT,
        action_type    TEXT,                   -- 유상증자 | 무상증자
        method         TEXT,                   -- 주주배정 | 제3자배정 | 일반공모 | 무상
        price_1st      INTEGER,                -- 1차 발행가
        price_2nd      INTEGER,
        price_final    INTEGER,                -- 확정 발행가
        old_shares     INTEGER,                -- 증자 전 발행주식총수
        new_shares     INTEGER,
        date_disclosure TEXT,                  -- 공시일 (rcept_dt)
        date_price_1st TEXT,                   -- 1차발행가 산정일
        date_record    TEXT,                   -- 신주배정기준일
        date_ex_rights TEXT,                   -- 권리락 (기준일-1거래일 파생)
        date_rights_listing_start TEXT,        -- 신주인수권증서 상장 시작
        date_rights_listing_end   TEXT,
        date_price_fix TEXT,                   -- 발행가 확정일
        date_sub_start TEXT,                   -- 구주주 청약 시작
        date_sub_end   TEXT,
        date_public_start TEXT,                -- 일반공모 시작
        date_public_end   TEXT,
        date_payment   TEXT,                   -- 납입일
        date_new_listing TEXT,                 -- 신주 상장(예정)일
        underwriter    TEXT,                   -- 주관사
        major_holder   TEXT,                   -- 최대주주 지분율/참여율
        extracted_at   TEXT DEFAULT (datetime('now'))
    );

    -- 엔티티 팔로우 — 팔로우 대상을 종목(watchlist)에서 임의 엔티티로 확장
    -- (섹터·테마 팔로우 → 홈 업데이트 스트림에 편입. 종목은 기존 watchlist 유지)
    CREATE TABLE IF NOT EXISTS follows (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_id    INTEGER NOT NULL UNIQUE REFERENCES entities(id) ON DELETE CASCADE,
        created_at   TEXT DEFAULT (datetime('now'))
    );

    -- 이미지 비전 분석 캐시 (이미지당 1회 — 증시일정표 → 이벤트 추출)
    CREATE TABLE IF NOT EXISTS media_analysis (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id       INTEGER NOT NULL REFERENCES raw_documents(id) ON DELETE CASCADE,
        image_path   TEXT NOT NULL UNIQUE,
        kind         TEXT,              -- calendar | chart | table | text | other
        description  TEXT,
        events_json  TEXT,
        model        TEXT,
        analyzed_at  TEXT DEFAULT (datetime('now'))
    );

    -- 전문 검색 (BM25) — raw_documents 외부 콘텐츠 방식 + 트리거 동기화.
    -- 벡터(doc_vec)는 sqlite-vec 확장이 필요해 pipeline/search.py에서 생성한다.
    CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(
        title, markdown, content='raw_documents', content_rowid='id'
    );
    CREATE TRIGGER IF NOT EXISTS raw_documents_ai AFTER INSERT ON raw_documents BEGIN
        INSERT INTO doc_fts(rowid, title, markdown) VALUES (new.id, new.title, new.markdown);
    END;
    CREATE TRIGGER IF NOT EXISTS raw_documents_ad AFTER DELETE ON raw_documents BEGIN
        INSERT INTO doc_fts(doc_fts, rowid, title, markdown) VALUES ('delete', old.id, old.title, old.markdown);
    END;
    CREATE TRIGGER IF NOT EXISTS raw_documents_au AFTER UPDATE ON raw_documents BEGIN
        INSERT INTO doc_fts(doc_fts, rowid, title, markdown) VALUES ('delete', old.id, old.title, old.markdown);
        INSERT INTO doc_fts(rowid, title, markdown) VALUES (new.id, new.title, new.markdown);
    END;

    -- 살아있는 모델: 파라미터화된 계산 스펙 (엑셀 continuity).
    CREATE TABLE IF NOT EXISTS models (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        name             TEXT NOT NULL UNIQUE,
        spec_json        TEXT,
        output_entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
        updated_at       TEXT DEFAULT (datetime('now'))
    );
    """)

    conn.commit()

    for migration in [
        "ALTER TABLE raw_documents ADD COLUMN media_json TEXT",
        "ALTER TABLE corporate_actions ADD COLUMN summary TEXT",
        "ALTER TABLE ir_notes ADD COLUMN memo_type TEXT DEFAULT 'general'",
        "ALTER TABLE telegram_channels ADD COLUMN is_active INTEGER DEFAULT 1",
        "ALTER TABLE telegram_channels ADD COLUMN last_fetched_at TEXT",
        "ALTER TABLE blog_sources ADD COLUMN is_active INTEGER DEFAULT 1",
        "ALTER TABLE blog_sources ADD COLUMN last_fetched_at TEXT",
        "ALTER TABLE blog_posts ADD COLUMN author TEXT",
        "ALTER TABLE blog_sources ADD COLUMN author TEXT",
        "ALTER TABLE entity_keywords ADD COLUMN status TEXT DEFAULT 'active'",
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
