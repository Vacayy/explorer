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

    # 사전 마이그레이션: 구 reports(anchor_topic PK, id 없음) → append-only(id PK)로 전환 (D-047).
    # reports는 재생성 가능한 캐시라 구 표는 버린다(id 생기면 재실행 안 됨). 히스토리는 이후부터 누적.
    try:
        rcols = [r[1] for r in conn.execute("PRAGMA table_info(reports)")]
        if rcols and "id" not in rcols:
            conn.execute("DROP TABLE reports")
            conn.commit()
    except Exception:
        pass

    # 사전 마이그레이션: us_movers 단일 스냅샷 → 일별 히스토리(D-095). 구표(trade_date 없음)는 재생성 가능한
    # 캐시라 폐기 — 히스토리는 이후부터 누적. (배경: docs/specs/us-briefing.md)
    try:
        mcols = [r[1] for r in conn.execute("PRAGMA table_info(us_movers)")]
        if mcols and "trade_date" not in mcols:
            conn.execute("DROP TABLE us_movers")
            conn.commit()
    except Exception:
        pass

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
        confidence     REAL,                          -- 이 인과 주장이 참이라는 확신 (효과 크기 아님, D-065)
        effect_strength TEXT,                          -- unknown|weak|moderate|strong (효과 크기 3단계, D-065·D-066)
        effect_direction TEXT,                         -- positive|negative|mixed (효과 방향, D-065)
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

    -- 리서치 후보 — 값싼 감지(RS 상승 ∩ 시총 ∩ 소속 섹터 화두)로 '파볼 만한' 종목 제안.
    -- 승인 시에만 opus 심층 리서치(stock_brief) 실행 — 비싼 노동을 사람 판단 뒤로 (D-020)
    CREATE TABLE IF NOT EXISTS research_candidates (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code       TEXT NOT NULL,
        entity_id        INTEGER REFERENCES entities(id) ON DELETE CASCADE,
        name             TEXT,
        detected_date    TEXT NOT NULL,          -- 감지 기준일
        rs_short         INTEGER,                 -- 단기 RS 백분위(현재)
        rs_short_prev    INTEGER,                 -- 1주 전 단기 RS
        market_cap       INTEGER,
        sector           TEXT,                    -- 화두인 소속 섹터
        share_delta_pp   REAL,                    -- 그 섹터의 theme_surge 점유율 상승폭
        status           TEXT DEFAULT 'proposed', -- proposed | done | dismissed
        revision_call    TEXT,                    -- 승인 리서치 결과(추정치 방향 콜 JSON)
        researched_at    TEXT,
        created_at       TEXT DEFAULT (datetime('now')),
        UNIQUE(stock_code, detected_date)
    );
    CREATE INDEX IF NOT EXISTS idx_research_cand_status ON research_candidates(status, detected_date);

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

    -- 텔레그램 연속 타이핑 판정 캐시 — 메시지당 1회 판정, 재수집 멱등성의 근간
    CREATE TABLE IF NOT EXISTS telegram_group_marks (
        channel    TEXT NOT NULL,
        msg_id     INTEGER NOT NULL,
        joins_prev INTEGER NOT NULL,   -- 1=직전 메시지의 연장, 0=별개
        model      TEXT,               -- judge(LLM) | gap(시간 fallback)
        judged_at  TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (channel, msg_id)
    );

    -- 종목 AI 브리프 (P2-1) — 도시에 첫 화면, 열람 시 게으른 생성 (inputs_hash 가드)
    -- append-only: 재생성마다 새 행 = 브리프 히스토리 (최신 = max(id))
    CREATE TABLE IF NOT EXISTS stock_briefs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_id    INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        brief        TEXT,                   -- 종합 브리프 (마크다운)
        thesis_check TEXT,                   -- 내 논지 vs 새 증거 충돌·지지 (없으면 NULL)
        inputs_hash  TEXT,                   -- 입력(다이제스트·신호·논지·일정) 변경 시에만 재생성
        model        TEXT,
        created_at   TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_stock_briefs_entity ON stock_briefs(entity_id, id);

    -- 투자 렌즈 판독 (docs/specs/investor-lens.md) — 원칙 원장에 비춘 종목 판단.
    -- append-only 히스토리(판단 변화 추적). principles/material 해시로 게으른 재생성 가드.
    CREATE TABLE IF NOT EXISTS lens_readings (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code      TEXT NOT NULL,
        market          TEXT NOT NULL DEFAULT 'kr',   -- kr | us
        lens_type       TEXT NOT NULL,                -- value | trend
        body            TEXT,                         -- 원칙에 비춘 판독 (마크다운)
        stance          TEXT,                         -- value: 강|중|약 / trend: 초입|진행|성숙|훼손
        signals_json    TEXT,                         -- 역추적용 근거
        principles_hash TEXT,                         -- 원장 버전 (바뀌면 stale)
        material_hash   TEXT,                         -- 재료 스냅샷 (바뀌면 재생성)
        model           TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_lens_readings ON lens_readings(stock_code, lens_type, id);

    -- 질문 종합 리포트 (docs 없음 — D-093) — 서브질문·판정·근거를 종합한 '현재 결산'.
    -- append-only 히스토리. inputs_hash로 게으른 재생성 가드(바뀔 때만 리포트→시나리오 체인 재실행).
    CREATE TABLE IF NOT EXISTS question_reports (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER NOT NULL,
        body        TEXT,                   -- 현재 결산 (마크다운)
        inputs_hash TEXT,                   -- 2층 판정·서브질문·프록시 관측·근거 스냅샷
        model       TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_question_reports ON question_reports(question_id, id);

    -- 미국 종목 데이터 (docs/specs/us-dossier.md, yfinance 캐시) — KR 도메인 테이블 오염 방지 위해 분리.
    -- 컬럼명은 stock_prices와 호환(stock_code=티커) → technicals·매물대 재사용.
    CREATE TABLE IF NOT EXISTS us_prices (
        stock_code TEXT NOT NULL,          -- 티커 (NVDA…) 또는 벤치마크(SPY)
        trade_date TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL, volume REAL,
        fetched_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY(stock_code, trade_date)
    );
    CREATE TABLE IF NOT EXISTS us_fundamentals (
        ticker     TEXT PRIMARY KEY,        -- yfinance info/income/cashflow/estimates 스냅샷
        data_json  TEXT NOT NULL,
        fetched_at TEXT NOT NULL
    );

    -- 전일 미국시장 거래대금(=종가×거래량) 상위 종목 — 일별 스냅샷 (TradingView 무키, docs/specs/us-briefing.md).
    -- 전 거래소 통합·ADR 포함·ETF 제외. 날짜별 누적(신규 진입 판정용, 최근 7일 보존). 캐시 게이트 cache_meta('us_movers_dollar_vol').
    CREATE TABLE IF NOT EXISTS us_movers (
        trade_date    TEXT NOT NULL,         -- 스냅샷 세션 날짜(US/Eastern)
        rank          INTEGER NOT NULL,      -- 1..N (거래대금 내림차순)
        ticker        TEXT NOT NULL,
        name          TEXT,
        close         REAL,
        volume        REAL,
        dollar_volume REAL,                  -- close × volume (USD)
        change_pct    REAL,                  -- 전일 등락률(%)
        sector        TEXT,                  -- TradingView sector (Electronic Technology …)
        industry      TEXT,                  -- TradingView industry (Semiconductors …)
        exchange      TEXT,                  -- NASDAQ | NYSE | AMEX | CBOE …
        market_cap    REAL,
        is_adr        INTEGER DEFAULT 0,     -- TradingView type='dr'
        is_new        INTEGER DEFAULT 0,     -- 직전 스냅샷 대비 신규 진입
        fetched_at    TEXT,
        PRIMARY KEY(trade_date, rank)
    );

    -- 국장 거래대금 상위 일별 스냅샷 (FDR KRX 리스팅, D-108) — us_movers의 국장 대응물.
    -- 섹터는 companies.sector(KSIC) → sector_map.group_name 대분류로 통일해 저장.
    CREATE TABLE IF NOT EXISTS kr_movers (
        trade_date    TEXT NOT NULL,         -- 스냅샷 세션 날짜(KST)
        rank          INTEGER NOT NULL,      -- 1..N (거래대금 내림차순)
        stock_code    TEXT NOT NULL,
        name          TEXT,
        market        TEXT,                  -- KOSPI | KOSDAQ | KONEX
        close         INTEGER,
        volume        INTEGER,
        value_traded  INTEGER,               -- 거래대금(원) — FDR Amount
        change_pct    REAL,                  -- 전일 등락률(%)
        sector        TEXT,                  -- sector_map.group_name 대분류
        market_cap    INTEGER,
        is_new        INTEGER DEFAULT 0,     -- 직전 스냅샷 대비 신규 진입
        fetched_at    TEXT,
        PRIMARY KEY(trade_date, rank)
    );

    -- 무버 종목별 US 원천 헤드라인 (yfinance .news 캐시, D-097) — 개별 종목 '왜' 채움.
    CREATE TABLE IF NOT EXISTS us_ticker_news (
        ticker       TEXT NOT NULL,
        url          TEXT NOT NULL,
        title        TEXT,
        publisher    TEXT,
        published_at TEXT,
        summary      TEXT,
        fetched_at   TEXT,
        PRIMARY KEY(ticker, url)
    );

    -- 매크로·유동성 신호등 해설 캐시 (D-102, sonnet 산문 · signature 불변이면 재사용, docs/specs/macro.md).
    CREATE TABLE IF NOT EXISTS macro_signals (
        as_of      TEXT PRIMARY KEY,       -- 스냅샷 기준일
        signature  TEXT NOT NULL,          -- 지표 값·변화율 해시 (재생성 게이트)
        signal     TEXT,                   -- green | yellow | red (신호등)
        headline   TEXT,
        comment    TEXT,
        model      TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- 어젯밤 미국장 브리핑 LLM 종합 캐시 (하루 1회·signature 불변이면 재사용, docs/specs/us-briefing.md).
    CREATE TABLE IF NOT EXISTS us_briefings (
        trade_date     TEXT PRIMARY KEY,
        signature      TEXT NOT NULL,        -- 구조화 요약 해시 (재생성 게이트)
        synthesis_json TEXT NOT NULL,        -- {mood, study_candidates, share_candidates}
        model          TEXT,
        created_at     TEXT DEFAULT (datetime('now'))
    );

    -- Peer 그룹 (LLM 큐레이션 1회 캐시) + 지표 캐시 (KR=자체, 해외=yfinance 24h)
    CREATE TABLE IF NOT EXISTS stock_peers (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code TEXT NOT NULL,
        name       TEXT NOT NULL,
        ticker     TEXT NOT NULL,          -- 야후 티커 (005930.KS, MU 등)
        market     TEXT NOT NULL,          -- KR | US | JP | ...
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(stock_code, ticker)
    );
    CREATE TABLE IF NOT EXISTS peer_metrics (
        ticker       TEXT PRIMARY KEY,
        metrics_json TEXT NOT NULL,
        fetched_at   TEXT NOT NULL
    );

    -- 지식 계층 (K0, knowledge-hierarchy-design.md) — 신피질: 승격된 통합 지식
    CREATE TABLE IF NOT EXISTS knowledge (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        statement        TEXT NOT NULL,
        epistemic_status TEXT NOT NULL DEFAULT 'observed',  -- observed|corroborated|contested|superseded|hypothesis
        review_status    TEXT NOT NULL DEFAULT 'proposed',  -- proposed|active|rejected (승인 큐)
        pace_layer       TEXT NOT NULL DEFAULT 'cycle',     -- event|flow|cycle|structure|regime (닫힌 어휘)
        confidence       REAL,
        valid_from       TEXT,
        valid_to         TEXT,
        supersedes       INTEGER REFERENCES knowledge(id),
        model            TEXT,
        created_at       TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS knowledge_entities (
        knowledge_id INTEGER NOT NULL REFERENCES knowledge(id) ON DELETE CASCADE,
        entity_id    INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        role         TEXT DEFAULT 'subject',
        UNIQUE(knowledge_id, entity_id)
    );
    CREATE TABLE IF NOT EXISTS knowledge_evidence (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        knowledge_id INTEGER NOT NULL REFERENCES knowledge(id) ON DELETE CASCADE,
        doc_id       INTEGER REFERENCES raw_documents(id) ON DELETE SET NULL,
        stance       TEXT NOT NULL DEFAULT 'support',   -- support|refute|attention(사용자 행위)
        independent  INTEGER NOT NULL DEFAULT 1,        -- 독립 관측 여부 (릴레이 접기)
        observed_at  TEXT NOT NULL                      -- activation 계산의 t
    );
    CREATE INDEX IF NOT EXISTS idx_knowledge_evidence ON knowledge_evidence(knowledge_id);
    -- K2 모순 감지: 문서-지식 대조를 문서당 1회만 (haiku 재판정 방지)
    CREATE TABLE IF NOT EXISTS knowledge_doc_scans (
        doc_id     INTEGER PRIMARY KEY REFERENCES raw_documents(id) ON DELETE CASCADE,
        scanned_at TEXT DEFAULT (datetime('now'))
    );
    -- 배치 실행 마커 — cron 누락 시 수집 체인이 catch-up 판단 (PC 꺼짐 대비)
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        name        TEXT PRIMARY KEY,
        last_run_at TEXT NOT NULL
    );
    -- 컨센서스 이력 (분해 v2 기반) — 투자자는 forward를 산다: Fwd EPS 추정치의
    -- 시계열이 쌓여야 revision(추정치 변화)과 리레이팅(멀티플 변화)을 가를 수 있다
    CREATE TABLE IF NOT EXISTS consensus_estimates (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code   TEXT NOT NULL,
        fetched_date TEXT NOT NULL,               -- 수집일 (일 1회)
        fiscal_year  TEXT NOT NULL,               -- 추정 회계연도 (예: '202612')
        fwd_eps      REAL,
        fwd_per      REAL,
        fwd_op       REAL,                        -- 영업이익 추정 (억원)
        fwd_revenue  REAL,
        fwd_roe      REAL,
        source       TEXT DEFAULT 'naver',
        UNIQUE(stock_code, fetched_date, fiscal_year)
    );
    CREATE INDEX IF NOT EXISTS idx_consensus_stock ON consensus_estimates(stock_code, fiscal_year, fetched_date);
    -- 수급 이력 (백로그 #23) — '누가 사고 있는가': 외인·기관·개인 순매수 (주식 수)
    CREATE TABLE IF NOT EXISTS investor_flows (
        stock_code   TEXT NOT NULL,
        trade_date   TEXT NOT NULL,               -- YYYY-MM-DD
        foreign_net  INTEGER,
        inst_net     INTEGER,
        indiv_net    INTEGER,
        foreign_hold_ratio REAL,
        close        INTEGER,
        PRIMARY KEY (stock_code, trade_date)
    );
    -- 유튜브 구독 채널 (신규 영상 자막 자동 수집)
    CREATE TABLE IF NOT EXISTS youtube_channels (
        channel_id  TEXT PRIMARY KEY,   -- UC…
        handle      TEXT,
        title       TEXT,
        is_active   INTEGER DEFAULT 1,
        last_fetched_at TEXT,
        added_at    TEXT DEFAULT (datetime('now'))
    );
    -- 특징일 설명 캐시 — 급등락일 원인 (마커 클릭 시 1콜, 영구 캐시)
    CREATE TABLE IF NOT EXISTS feature_day_notes (
        stock_code TEXT NOT NULL,
        date       TEXT NOT NULL,
        note       TEXT,               -- NULL이면 status 참조 (no_docs 등)
        status     TEXT NOT NULL,      -- ok | no_docs | failed
        model      TEXT,
        created_at TEXT,
        PRIMARY KEY (stock_code, date)
    );
    -- 밸류체인 구조 (맵 v2) — 대분류별 단계·테마 (LLM 시드)
    CREATE TABLE IF NOT EXISTS value_chains (
        group_name  TEXT NOT NULL,
        stage_idx   INTEGER NOT NULL,
        stage_name  TEXT NOT NULL,
        themes_json TEXT NOT NULL,     -- ["테마", ...]
        PRIMARY KEY (group_name, stage_idx)
    );
    -- 섹터 맵: KSIC 세분류(165) → 투자 언어 대분류 (LLM 1회 큐레이션 시드)
    CREATE TABLE IF NOT EXISTS sector_map (
        sector_name TEXT PRIMARY KEY,   -- entities(type='sector').name (KSIC)
        group_name  TEXT NOT NULL       -- 대분류 (반도체·전자부품, 바이오·헬스케어 등)
    );
    -- 반증 조건 (지능 업그레이드 1): 지식마다 '틀렸다는 신호'를 명시하고 표적 감시
    CREATE TABLE IF NOT EXISTS knowledge_falsifiers (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        knowledge_id INTEGER NOT NULL REFERENCES knowledge(id) ON DELETE CASCADE,
        condition    TEXT NOT NULL,               -- 관측 가능한 반증 신호 서술
        triggered_at TEXT,                        -- 감지 시각 (NULL=미발화)
        triggered_doc_id INTEGER REFERENCES raw_documents(id) ON DELETE SET NULL,
        created_at   TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_falsifiers_knowledge ON knowledge_falsifiers(knowledge_id);

    -- 대화 영속화 (P2-0, docs/specs/product-v3.md §2) — 질문·후속질문 = 사용자 의도 데이터
    -- 에코챔버 방지: chat_messages는 검색 인덱스(doc_fts/doc_vec) 대상이 아니다
    CREATE TABLE IF NOT EXISTS conversations (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        title            TEXT,                   -- 첫 질문 앞 60자 (자동)
        anchor_entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
        channel          TEXT NOT NULL DEFAULT 'web',  -- web | telegram
        chat_id          TEXT,                   -- 텔레그램 사용자 분리 (웹/오너=NULL)
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

    -- 내러티브 (1급 객체, 버전 보존) — 인과 그래프 위의 시간순 서브그래프 (D-023)
    CREATE TABLE IF NOT EXISTS narratives (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        topic         TEXT NOT NULL,          -- theme/sector 이름 (생성 앵커)
        version       INTEGER NOT NULL,       -- topic별 1,2,3…
        title         TEXT,                   -- 질문형 제목
        body          TEXT,                   -- md 본문
        category      TEXT,                   -- 도메인 렌즈 CSV (macro|geopolitics|industry|flow|tech|policy)
        doc_count     INTEGER,
        doc_ids_hash  TEXT,                   -- 재생성 가드
        model         TEXT,
        created_at    TEXT DEFAULT (datetime('now')),
        superseded_at TEXT,                   -- 새 버전 나오면 닫음 (삭제 없음 — 드리프트 추적)
        UNIQUE(topic, version)
    );

    -- 에이전트 제안함 (진화계획 3단계 v1, docs/specs/agent-proposals.md) — 시스템이 그래프·지식
    -- 상태를 감시하다 먼저 "조사해볼까요?"를 던진다. 제안-전용: 승인 전엔 어떤 행동도 없음.
    CREATE TABLE IF NOT EXISTS agent_proposals (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        kind          TEXT NOT NULL,        -- neglect|contested_edge|devils_advocate|falsifier_watch
        title         TEXT NOT NULL,        -- 제안형 한 줄
        rationale     TEXT,                 -- 왜 이걸 제안하는지 (승인 전 읽는 근거)
        payload_json  TEXT,                 -- kind별 구조화 데이터 (entity_id·edge_id·knowledge_id 등)
        dedup_key     TEXT,                 -- kind별 중복 방지 키 (같은 대상 재제안 억제)
        status        TEXT DEFAULT 'proposed',  -- proposed|dismissed|actioned
        detected_at   TEXT DEFAULT (datetime('now')),
        actioned_at   TEXT,
        result_json   TEXT,                 -- 승인 후 실행 결과 요약
        UNIQUE(kind, dedup_key)
    );
    CREATE INDEX IF NOT EXISTS idx_agent_proposals_status ON agent_proposals(status, detected_at);

    -- 인과 엣지 근거 이력 (Phase 2 §2-4 교차검증) — entity_relations.narrative_id는 "가장 최근"
    -- 하나만 남기므로(재적재 시 덮어씀), 몇 개의 '독립' 내러티브가 이 엣지를 주장했는지 세려면
    -- 매 적재·재적재마다의 (엣지, 내러티브) 쌍을 별도로 누적해야 한다.
    CREATE TABLE IF NOT EXISTS narrative_edge_evidence (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_relation_id INTEGER NOT NULL,
        narrative_id       INTEGER NOT NULL,
        created_at         TEXT DEFAULT (datetime('now')),
        UNIQUE(entity_relation_id, narrative_id)
    );
    CREATE INDEX IF NOT EXISTS idx_nee_relation ON narrative_edge_evidence(entity_relation_id);
    CREATE INDEX IF NOT EXISTS idx_narratives_topic ON narratives(topic, version);

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

    -- 저장됨(북마크) — 특정 산출물(기업·문서·내러티브·리포트) 다시 찾기 (D-078)
    -- 내러티브·리포트는 버전 행 PK를 ref로 저장(보던 그 버전 고정). UNIQUE(kind, ref)로 토글 멱등.
    CREATE TABLE IF NOT EXISTS saved_items (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        kind         TEXT NOT NULL,          -- company | doc | narrative | report | synthesis
        ref          TEXT NOT NULL,          -- stockCode | docId | narrative_id | report id | synthesis id
        url          TEXT NOT NULL,
        title        TEXT,
        subtitle     TEXT,
        note         TEXT,
        created_at   TEXT DEFAULT (datetime('now')),
        UNIQUE(kind, ref)
    );

    -- 문서 교차 종합 — 사람이 고른 문서 묶음을 엮어 읽은 산출물 (D-104, docs/specs/doc-synthesis.md)
    -- 일회성: 묶음 객체 없음. 같은 조합 재생성은 새 행(append-only 히스토리).
    CREATE TABLE IF NOT EXISTS doc_syntheses (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_ids      TEXT NOT NULL,          -- json 배열(정렬된 raw_documents.id) — 무엇을 엮었나 스냅샷
        title        TEXT,
        body         TEXT NOT NULL,          -- 마크다운 산출물
        model        TEXT,
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

    -- 파급 시나리오 캐시 (D-038) — topic별 opus 결과 저장, 기반 내러티브 버전 변동 시에만 재생성.
    -- upside 캐시(models)와 같은 철학: 매 클릭 opus 재생성 방지, 명시적 '다시 분석'으로만 갱신.
    CREATE TABLE IF NOT EXISTS scenarios (
        topic             TEXT PRIMARY KEY,
        event             TEXT,
        answer            TEXT,
        beneficiaries     TEXT,    -- json
        citations         TEXT,    -- json
        narrative_version INTEGER, -- 기반 내러티브 버전 (변동 시 stale)
        model             TEXT,
        created_at        TEXT DEFAULT (datetime('now'))
    );

    -- 통합 리포트 캐시 (integrated-report) — 앵커 주제 + 공유 이웃 내러티브 취합 → 종목 다각도
    -- 재분석 → Top-down 리포트. members_hash(구성원 topic:version)로 멱등, 구성원 변동 시 stale.
    CREATE TABLE IF NOT EXISTS reports (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,   -- append-only 버전 (D-047 히스토리)
        anchor_topic  TEXT NOT NULL,
        title         TEXT,
        body          TEXT,        -- Top-down 마크다운
        members_json  TEXT,        -- 취합된 내러티브 topic 목록 (json)
        stocks_json   TEXT,        -- 분석 종목 [{code,name,rating,upside_pct}] (json)
        debate_json   TEXT,        -- analyst·bull·bear·ratings 산출물 (열람)
        members_hash  TEXT,        -- 재생성 가드
        top_pick      TEXT,        -- Top-pick 종목코드 (A, 단일 종목 심층)
        model         TEXT,
        created_at    TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_reports_topic ON reports(anchor_topic, id);

    -- 운영 관리 (관리자 페이지, D-055) — cron 작업 on/off + 실행 로그.
    CREATE TABLE IF NOT EXISTS feature_flags (
        name       TEXT PRIMARY KEY,
        enabled    INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS job_runs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        job         TEXT NOT NULL,
        status      TEXT NOT NULL,   -- ok | skipped | error
        summary     TEXT,
        duration_ms INTEGER,
        ran_at      TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_job_runs ON job_runs(id);

    -- 시장 국면 (market regime, D-076, docs/specs/market-regime.md) — 매크로 리스크 포스처.
    -- 일별 스냅샷(EOD): F&G·VIX·S&P·KOSPI·20EMA·VKOSPI/실현변동성. 스파크라인 히스토리 = 축적.
    -- 지표 = fact (hypothesis 아님). 포스처 결합은 API에서 결정적 계산(LLM 0), 여기엔 원지표만.
    CREATE TABLE IF NOT EXISTS market_indicators (
        snapshot_date TEXT NOT NULL,        -- KST YYYY-MM-DD
        indicator     TEXT NOT NULL,        -- fear_greed | vix | sp500 | kospi | kospi_ema20 | vkospi | kospi_vol
        value         REAL,
        extra_json    TEXT,                 -- rating·band 등 부수 (nullable)
        PRIMARY KEY (snapshot_date, indicator)
    );
    CREATE INDEX IF NOT EXISTS idx_market_ind ON market_indicators(indicator, snapshot_date);

    -- 논지 감사 (thesis audit, docs/specs/thesis-audit.md) — thesis를 인과그래프에 대질한 read-only 감사 결과.
    -- append-only 히스토리(판단이 시간에 따라 어떻게 변했나). 사용자 주장은 여기 저장되지 그래프에 안 써진다(격리).
    CREATE TABLE IF NOT EXISTS thesis_audits (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        thesis_text TEXT NOT NULL,
        result_json TEXT NOT NULL,       -- 주장별 델타(판정·근거 엣지·내러티브·시간)
        created_at  TEXT DEFAULT (datetime('now'))
    );

    -- 어휘 통합 (vocab consolidation, D-033) — audit + redirect 겸용.
    -- 배치 병합으로 사라진 theme/macro 노드 이름이 재등장해도 survivor로 해소 (재파편화 방지).
    CREATE TABLE IF NOT EXISTS entity_merges (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        old_name     TEXT NOT NULL,       -- 병합으로 사라진 노드 이름
        type         TEXT NOT NULL,       -- theme | macro (v1 범위)
        survivor_id  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        rationale    TEXT,                -- LLM 판정 근거
        merged_at    TEXT DEFAULT (datetime('now')),
        UNIQUE(old_name, type)
    );

    -- Transcript 팔로우 (미국 기업 실적 컨콜, docs/specs/transcript-follow.md) — 기업 단위 구독
    CREATE TABLE IF NOT EXISTS transcript_follow (
        ticker        TEXT PRIMARY KEY,     -- 미국 티커 (AAPL, NVDA, CRWV ...)
        company_name  TEXT NOT NULL,
        entity_id     INTEGER,              -- entities 연결(있으면) — 유니버스/팔로우와 크로스링크
        group_label   TEXT,                 -- M7 | hyperscaler | ai-datacenter | energy | cpo | web3 ...
        active        INTEGER DEFAULT 1,
        added_at      TEXT DEFAULT (datetime('now'))
    );

    -- transcript 인덱스 (얇은 메타) — 전문(body)은 raw_documents(source_type='transcript')에 있고
    -- 인과·정리·임베딩은 그 raw_documents 행을 통해 기존 파이프라인에 흐른다. 여기선 중복 저장 안 함.
    CREATE TABLE IF NOT EXISTS transcripts (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_doc_id    INTEGER NOT NULL,     -- FK raw_documents.id
        ticker        TEXT NOT NULL,
        fiscal_year   INTEGER,
        fiscal_period TEXT,                 -- Q1..Q4 | FY
        call_date     TEXT,
        provider      TEXT,                 -- 어느 어댑터로 수집했는지
        fetched_at    TEXT DEFAULT (datetime('now')),
        UNIQUE(ticker, fiscal_year, fiscal_period)
    );

    -- 빈응답 네거티브 캐시 (D-081) — AV는 dates 엔드포인트가 없어 분기를 probe하는데,
    -- 빈응답(커버리지 공백·미보고)을 기억해 쿨다운 동안 재요청 안 함 → 25/day 예산 낭비 차단.
    CREATE TABLE IF NOT EXISTS transcript_probe (
        ticker        TEXT NOT NULL,
        fiscal_year   INTEGER NOT NULL,
        fiscal_period TEXT NOT NULL,
        attempts      INTEGER DEFAULT 1,
        checked_at    TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (ticker, fiscal_year, fiscal_period)
    );

    -- 실적 발표일 캘린더 (D-081) — yfinance(무료, AV 예산과 무관)로 최근/차기 보고일 캐시.
    -- 라운드로빈이 '아직 안 나온 분기'(quarter_end > last_report_date)를 probe 안 하게 게이트.
    CREATE TABLE IF NOT EXISTS transcript_calendar (
        ticker           TEXT PRIMARY KEY,
        last_report_date TEXT,              -- 최근 실적 발표일 (ISO date)
        next_report_date TEXT,              -- 차기 예정 발표일
        checked_at       TEXT DEFAULT (datetime('now'))
    );

    -- 프록시 레지스트리 (사람이 세팅 — "무엇을 볼지") — 리포트 핵심질문(D-049)의 관찰 프록시
    CREATE TABLE IF NOT EXISTS proxy_registry (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        key           TEXT NOT NULL UNIQUE, -- hyperscaler_capex | oai_arr ...
        label         TEXT NOT NULL,        -- '하이퍼스케일러 CAPEX 추이'
        narrative_id  INTEGER,              -- 어느 지배 내러티브의 프록시인가
        tickers       TEXT,                 -- 관련 티커 CSV (추출 대상 컨콜)
        unit          TEXT,                 -- $B | % | MW ...
        extract_hint  TEXT,                 -- 추출용 프롬프트 힌트
        active        INTEGER DEFAULT 1,
        created_at    TEXT DEFAULT (datetime('now'))
    );

    -- 프록시 관측치 (기계가 트래킹 — transcript에서 추출한 값, 시계열)
    CREATE TABLE IF NOT EXISTS proxy_observations (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        proxy_id      INTEGER NOT NULL,
        transcript_id INTEGER,              -- 출처 컨콜 (추적성)
        observed_at   TEXT,                 -- 관측 시점(컨콜 날짜)
        value_num     REAL,                 -- 파싱된 수치(가능하면)
        value_text    TEXT,                 -- 원문 인용/맥락
        direction     TEXT,                 -- up | down | flat
        confidence    REAL,
        created_at    TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_transcripts_ticker ON transcripts(ticker, fiscal_year, fiscal_period);
    CREATE INDEX IF NOT EXISTS idx_proxy_obs ON proxy_observations(proxy_id, observed_at);

    -- 핵심질문 트래커 (D-067·D-068, docs/specs/question-proxy.md) — 분할정복:
    -- 질문 → 서브질문 → 프록시 → 관측 → 판정. 질문 = 지식의 미결 버전(판정되면 knowledge로 승격).
    CREATE TABLE IF NOT EXISTS questions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        text            TEXT NOT NULL,
        narrative_id    INTEGER,              -- 도출 출처 내러티브 (사용자 주입이면 NULL)
        source_doc_id   INTEGER,              -- Q5: 단일 소스에서 출발한 경우 그 문서
        created_by      TEXT NOT NULL DEFAULT 'user',      -- system(내러티브 도출) | user(주입)
        status          TEXT NOT NULL DEFAULT 'tracking',  -- proposed | tracking | resolved | dismissed
        lead_verdict    TEXT,                 -- 선행 판정 (fast: sentiment·stance) leaning_yes|leaning_no|mixed|unknown
        confirm_verdict TEXT,                 -- 확정 판정 (slow: numeric)
        divergence      TEXT,                 -- aligned | lead_ahead | confirm_ahead (D-068)
        verdict_summary TEXT,                 -- 게으른 LLM 한 줄 종합 (하이브리드 판정의 서술부)
        conviction      REAL,                 -- knowledge_state 재사용 (판정 강도)
        salience        REAL,                 -- 시장 주목
        created_at      TEXT DEFAULT (datetime('now')),
        updated_at      TEXT DEFAULT (datetime('now'))
    );
    -- 서브질문 (논리적 분할, 각 반증조건 보유) — "이걸 보려면"
    CREATE TABLE IF NOT EXISTS sub_questions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id  INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
        text         TEXT NOT NULL,
        falsifier    TEXT,                    -- 반증조건: 이 방향 관측이면 핵심질문이 틀린 것
        verdict      TEXT,                    -- 서브질문 단위 판정 (프록시 관측 롤업)
        weight       REAL DEFAULT 1.0,
        created_at   TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_sub_questions ON sub_questions(question_id);

    -- 수출입(무역) 팔로우 (docs/specs/trade-follow.md, 관세청 품목별 수출입실적) — 관심 품목 구독
    CREATE TABLE IF NOT EXISTS trade_follow (
        hs_code       TEXT PRIMARY KEY,     -- HS 부호 (2·4단위 혼용, 예 '8542'=반도체)
        item_name     TEXT NOT NULL,
        group_label   TEXT,                 -- IT·자동차·소재·에너지 ...
        active        INTEGER DEFAULT 1,
        added_at      TEXT DEFAULT (datetime('now'))
    );

    -- 품목별 월별 수출입 통계 (추이 시계열)
    CREATE TABLE IF NOT EXISTS trade_stats (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        hs_code       TEXT NOT NULL,
        period        TEXT NOT NULL,        -- 'YYYY-MM'
        export_usd    REAL,
        import_usd    REAL,
        export_wt     REAL,
        import_wt     REAL,
        balance_usd   REAL,                 -- 무역수지 (수출-수입)
        fetched_at    TEXT DEFAULT (datetime('now')),
        UNIQUE(hs_code, period)
    );

    -- 품목 관련 종목 (LLM 논리 지목 캐시, scenario/beneficiary와 동일 철학 — D-036)
    CREATE TABLE IF NOT EXISTS trade_beneficiaries (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        hs_code       TEXT NOT NULL,
        stock_code    TEXT,
        name          TEXT,
        rel           TEXT,                 -- 수혜 | 피해
        reason        TEXT,
        rs REAL, per REAL, mktcap REAL, pos_52w REAL,
        in_universe   INTEGER, universe_groups TEXT,
        computed_at   TEXT DEFAULT (datetime('now')),
        UNIQUE(hs_code, name)
    );
    CREATE INDEX IF NOT EXISTS idx_trade_stats ON trade_stats(hs_code, period);
    """)

    conn.commit()

    for migration in [
        "ALTER TABLE raw_documents ADD COLUMN media_json TEXT",
        "ALTER TABLE conversations ADD COLUMN chat_id TEXT",  # 사용자 분리 (텔레그램 chat_id, 웹=NULL=오너)
        "ALTER TABLE fundamentals ADD COLUMN roe REAL",  # 전종목 밸류 수집 (네이버 시세)
        "ALTER TABLE corporate_actions ADD COLUMN summary TEXT",
        "ALTER TABLE ir_notes ADD COLUMN memo_type TEXT DEFAULT 'general'",
        "ALTER TABLE telegram_channels ADD COLUMN is_active INTEGER DEFAULT 1",
        "ALTER TABLE telegram_channels ADD COLUMN last_fetched_at TEXT",
        "ALTER TABLE blog_sources ADD COLUMN is_active INTEGER DEFAULT 1",
        "ALTER TABLE blog_sources ADD COLUMN last_fetched_at TEXT",
        "ALTER TABLE blog_posts ADD COLUMN author TEXT",
        "ALTER TABLE blog_sources ADD COLUMN author TEXT",
        "ALTER TABLE entity_keywords ADD COLUMN status TEXT DEFAULT 'active'",
        "ALTER TABLE knowledge ADD COLUMN contested_at TEXT",  # K2: contested 전환 시각 (알림 쿨다운 기준)
        "ALTER TABLE knowledge ADD COLUMN corroborated_at TEXT",  # K3: 승격 시각 (사용자 가설 확인 알림)
        "ALTER TABLE consensus_estimates ADD COLUMN target_price REAL",  # 목표주가 평균 (integration API)
        "ALTER TABLE consensus_estimates ADD COLUMN opinion REAL",       # 투자의견 평균 (5점 척도)
        "ALTER TABLE stock_briefs ADD COLUMN revision_call TEXT",  # 추정치 방향 콜 JSON {direction, rationale}
        # 시간 정박(D-021): 발행일≠사건 발생일. 글이 가리키는 시간 방향·시기 분리
        "ALTER TABLE enrichments ADD COLUMN time_orientation TEXT",  # past|current|forward|mixed
        "ALTER TABLE enrichments ADD COLUMN reference_period TEXT",  # 발행일과 다른 실제 대상 시기 (예: '2026 2분기', '2027 전망')
        "ALTER TABLE knowledge ADD COLUMN rationale TEXT",   # 사용자 주입 근거 ('왜 믿나')
        "ALTER TABLE knowledge ADD COLUMN source_ref TEXT",  # 사용자 주입 출처 ('누가 말했나')
        "ALTER TABLE knowledge_falsifiers ADD COLUMN target_entity TEXT",  # 반증 감시 대상 (구조화)
        "ALTER TABLE knowledge_falsifiers ADD COLUMN metric TEXT",         # 관측 지표
        "ALTER TABLE knowledge_falsifiers ADD COLUMN threshold TEXT",      # 임계
        "ALTER TABLE knowledge_falsifiers ADD COLUMN window TEXT",         # 관측 기간
        "ALTER TABLE entity_relations ADD COLUMN mechanism TEXT",          # 인과 엣지 서사 (D-023)
        "ALTER TABLE entity_relations ADD COLUMN reference_period TEXT",   # 이 인과가 작동하는 시점 (D-021)
        "ALTER TABLE entity_relations ADD COLUMN time_orientation TEXT",   # past|current|forward (시간 그래디언트)
        "ALTER TABLE entity_relations ADD COLUMN narrative_id INTEGER",    # 어느 내러티브(버전)에서 나왔나
        "ALTER TABLE entity_relations ADD COLUMN promoted_knowledge_id INTEGER",  # 승격된 지식(Phase 2 §2-5)
        "ALTER TABLE entity_relations ADD COLUMN feedback_note TEXT",  # both_temporal 판정 물질화 — 상충 아닌 시점 다른 피드백 나선(D-027) 근거, non-null=해소됨(D-029)
        "ALTER TABLE entity_relations ADD COLUMN geo_scope TEXT",  # 인과 주장의 장소 스코프 (통제어휘 GEO_VOCAB, D-034)
        "ALTER TABLE entity_relations ADD COLUMN effect_strength TEXT",   # 효과 크기 unknown|weak|moderate|strong — 확신과 별개 축 (D-065, 3단계 D-066)
        "ALTER TABLE entity_relations ADD COLUMN effect_direction TEXT",  # 효과 방향 positive|negative|mixed (D-065)
        # 메르식 서사 (Phase 2 §2-2) — 순회 top-1 경로를 opus가 하나의 흐르는 글로
        "ALTER TABLE narratives ADD COLUMN mer_body TEXT",
        "ALTER TABLE narratives ADD COLUMN mer_path_hash TEXT",  # 경로 변경 시에만 재생성 (가드)
        "ALTER TABLE narratives ADD COLUMN drift_summary TEXT",  # 직전 버전 대비 변화 한 줄 (Phase 2 §2-3)
        # 메가 내러티브 층 (D-031) — 공유노드 군집의 상위 세계관 서사. kind='mega'면
        # topic=군집 라벨(LLM 명명), members_json=구성 sub-story 토픽들, doc_ids_hash=멤버 해시
        "ALTER TABLE narratives ADD COLUMN kind TEXT DEFAULT 'topic'",   # topic | mega
        "ALTER TABLE narratives ADD COLUMN members_json TEXT",
        "ALTER TABLE raw_documents ADD COLUMN digest_status TEXT",  # youtube opus 정리본 성공 여부 (ok|failed, 그 외 소스는 NULL)
        # 문서 레벨 인과 추출 (D-028 레버 3) — 시도 기록(인과 0건이어도), 재시도 방지
        "ALTER TABLE enrichments ADD COLUMN causal_extracted_at TEXT",
        # 리포트 v2 다중 에이전트(report-v2-agents) — debate 산출물 보존·열람 (analyst·bull·bear·레이팅)
        "ALTER TABLE reports ADD COLUMN debate_json TEXT",
        # transcript 핵심 정리(D-061 stage 2) — 원문(raw_documents)은 그대로 두고 별도 LLM 정리 저장
        "ALTER TABLE transcripts ADD COLUMN digest TEXT",
        # 핵심질문 트래커(D-067·D-068) — 프록시를 서브질문에 바인딩 + 다양식(pace layer) + 관측 다소스화
        "ALTER TABLE proxy_registry ADD COLUMN sub_question_id INTEGER",           # 어느 서브질문의 프록시인가
        "ALTER TABLE proxy_registry ADD COLUMN modality TEXT DEFAULT 'numeric'",   # numeric|sentiment|stance (pace layer)
        "ALTER TABLE proxy_registry ADD COLUMN yes_direction TEXT",                # 'up'|'down' — 어느 관측 방향이 핵심질문 '예'의 근거인가(판정 극성)
        "ALTER TABLE scenarios ADD COLUMN question_id INTEGER",                     # 질문=허브(D-070): Q5 시나리오를 질문에 묶음(NULL=내러티브발)
        "ALTER TABLE questions ADD COLUMN last_viewed_at TEXT",                     # 관측 비용 게이트(D-072): 최근 조회 질문만 자동 관측(dormant 일시정지)
        "ALTER TABLE proxy_observations ADD COLUMN source_type TEXT",              # 범용 source_ref (transcript|financial|consensus|signal)
        "ALTER TABLE proxy_observations ADD COLUMN source_id TEXT",
        "ALTER TABLE entity_digests ADD COLUMN insight_proposed INTEGER DEFAULT 0",  # 다이제스트 언섬(D-085): insight를 질문 제안 큐로 흘린 dedup 플래그
        # 관측→엣지 환류 (D-087) — 추적 질문이 confirm=leaning_yes+aligned 도달 시 딛고 선 내러티브 엣지에
        # 관측 확증 주석. confidence(인과 확신)와 별개 축(축 분리 D-022/D-065) — 실데이터로 확인됐나.
        "ALTER TABLE entity_relations ADD COLUMN obs_confirmed_at TEXT",
        "ALTER TABLE entity_relations ADD COLUMN obs_confirmed_qid INTEGER",
        "ALTER TABLE questions ADD COLUMN edge_confirmed INTEGER DEFAULT 0",  # 확증 상태 진입 1회 발화 가드(멱등)
        "ALTER TABLE market_indicators ADD COLUMN fetched_at TEXT",  # 수집 시각(UTC) — 지수별 '언제 받은 값인가' 표시 (D-110)
        # 내러티브 제목이 주장형이 되며 분리된 '관통 질문' — 질문 트래커 후보 공급용 (D-120).
        # 구 버전 행은 NULL이고 그 시절 title이 질문형이라 소비처가 COALESCE로 흡수한다(백필 없음).
        "ALTER TABLE narratives ADD COLUMN core_question TEXT",
        # 수집 게이트 (D-126) — `is_active`는 **개인 노출(뮤트)** 축이라 수집을 멈추지 않는다
        # (PHILOSOPHY §1 "수집=공공재 / 판단=개인" 분리). 수집 자체를 끄는 별도 축이 필요했다.
        "ALTER TABLE blog_sources ADD COLUMN collect_enabled INTEGER DEFAULT 1",
        "ALTER TABLE telegram_channels ADD COLUMN collect_enabled INTEGER DEFAULT 1",
        "ALTER TABLE youtube_channels ADD COLUMN collect_enabled INTEGER DEFAULT 1",
    ]:
        try:
            conn.execute(migration)
            conn.commit()
        except Exception:
            pass

    # 백필: digest_status 컬럼 신설 이전 유튜브 문서는 opus 정리본 마커로 상태 역산
    conn.execute(
        "UPDATE raw_documents SET digest_status='ok' WHERE source_type='youtube' "
        "AND digest_status IS NULL AND raw_content LIKE '%opus 정리본%'")
    conn.execute(
        "UPDATE raw_documents SET digest_status='failed' WHERE source_type='youtube' "
        "AND digest_status IS NULL AND raw_content NOT LIKE '%opus 정리본%'")
    conn.commit()

    # 프록시 관측 다소스화 백필 (D-067) — 기존 transcript_id를 범용 source_ref로 (7건 보존)
    conn.execute(
        "UPDATE proxy_observations SET source_type='transcript', source_id=CAST(transcript_id AS TEXT) "
        "WHERE source_type IS NULL AND transcript_id IS NOT NULL")
    # transcript_follow.entity_id 백필 (D-067 2c) — observations 투영 전제. 정확 매칭만(Meta→MetaMask 오매칭 회피)
    conn.execute(
        "UPDATE transcript_follow SET entity_id = ("
        "  SELECT e.id FROM entities e WHERE e.type='company' AND e.name = transcript_follow.company_name LIMIT 1) "
        "WHERE entity_id IS NULL")
    conn.commit()

    # narrative_edge_evidence 백필 — 과거엔 narrative_id가 최근 갱신 하나만 남겨 이전 재적재
    # 이력이 유실됐다. 최소 1건(현재 태그)은 근거로 잡아 corroborated_by가 0으로 보이지
    # 않게 한다(멱등, INSERT OR IGNORE + UNIQUE).
    conn.execute("""
        INSERT OR IGNORE INTO narrative_edge_evidence (entity_relation_id, narrative_id)
        SELECT id, narrative_id FROM entity_relations
        WHERE narrative_id IS NOT NULL AND rel_type IN ('CAUSES','BENEFITS_FROM')
    """)
    conn.commit()

    # stock_briefs: UNIQUE(entity_id) 제거 → append-only 히스토리 (1회성 재생성)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='stock_briefs'").fetchone()
    if row and "UNIQUE" in (row[0] or ""):
        conn.executescript("""
            ALTER TABLE stock_briefs RENAME TO stock_briefs_old;
            CREATE TABLE stock_briefs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id    INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                brief        TEXT,
                thesis_check TEXT,
                inputs_hash  TEXT,
                model        TEXT,
                created_at   TEXT DEFAULT (datetime('now'))
            );
            INSERT INTO stock_briefs (entity_id, brief, thesis_check, inputs_hash, model, created_at)
                SELECT entity_id, brief, thesis_check, inputs_hash, model, created_at FROM stock_briefs_old;
            DROP TABLE stock_briefs_old;
            CREATE INDEX IF NOT EXISTS idx_stock_briefs_entity ON stock_briefs(entity_id, id);
        """)
        conn.commit()

    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized.")
