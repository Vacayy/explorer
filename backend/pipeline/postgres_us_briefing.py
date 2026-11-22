"""The US briefing read from PG (single-path candidate), without the projection file.

The rows the legacy briefing reads are taken from the ledger view (legacy_snapshot_rows: snapshot, supplement,
overlays, revisions) into a private in-memory SQLite file per request, with the owner's ledgers laid over them the way
the projection builder does (transcript follows, row overrides, candidate run records), and the legacy computation
(pipeline.us_briefing.build_briefing) runs on that file unchanged. Only the rows it can reach are loaded:

- whole: us_movers, us_briefings, transcript_follow, macro_signals (small tables)
  (a past day without its movers snapshot reads only the stored synthesis: nothing else is loaded)
- job_runs: the 06:30 briefing's own records (compute_briefing)
- market_indicators: the newest SERIES_ROWS rows of each series the briefing and the macro leader read
- raw_documents of the briefing day and of the mention/news windows (recent days), with their links and enrichments
- entities: the ones those documents link and the company names and tickers the movers resolve through
- entity_relations: the narrative relations of those entities, and those narratives
- us_ticker_news: the movers' tickers, recent days (and undated)
"""
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

TABLES = ('us_movers', 'us_briefings', 'narratives', 'transcript_follow', 'macro_signals', 'job_runs',
          'market_indicators', 'raw_documents', 'entity_links', 'enrichments', 'entities', 'entity_relations',
          'us_ticker_news')
SERIES_ROWS = 100  # the briefing reads at most 70 rows of a macro series and 2 of an index
WINDOW_DAYS = 4    # documents and headlines: the 3-day windows (40 hours for mentions), a day of margin


def _indicators():
    from pipeline import indicator_canon, macro, us_briefing
    return sorted({f'macro_{name}' for name in [*macro.YF, *macro.FRED]}
                  | {indicator_canon.CANONICAL[name] for name in macro.CANON_RATES} | set(us_briefing._INDEX_KR))


def load(pg, now=None, trade_date=None, spent=None):
    """The in-memory file the briefing reads (sqlite3.Row rows, like the projection's connections). For a past
    `trade_date` without its movers snapshot only the stored synthesis is read, so only it is loaded. `spent` collects
    the time in PG reads and in filling the file, and the rows loaded."""
    spent = spent if spent is not None else {}
    spent.update(pg_ms=0.0, insert_ms=0.0, rows=0)
    # Each request has its own connection, so JIT would compile every view query again: 2.5 s on a first request,
    # 0.3 s without it (2026-11-22). The settings are pipeline.postgres_screen_reads.prepare's.
    from pipeline.postgres_screen_reads import prepare
    prepare(pg)
    from pipeline import us_briefing
    from pipeline.postgres_candidate_job_runs import COLUMNS as RUN_COLUMNS
    from pipeline.postgres_legacy_projection import derive_owner_transcript_follow
    from pipeline.postgres_owner_overrides import OVERRIDES, derive as derive_overrides
    mem = sqlite3.connect(':memory:', check_same_thread=False)
    mem.row_factory = sqlite3.Row
    for _name, ddl in pg.execute('SELECT table_name, schema_sql FROM legacy_snapshot_tables WHERE table_name = ANY(%s)',
                                 (list(TABLES),)):
        mem.execute(ddl)
    columns = {table: [row[1] for row in mem.execute(f'PRAGMA table_info("{table}")')] for table in TABLES}

    clock = time.perf_counter

    def rows(table, where='', args=()):
        started = clock()
        found = [row for (row,) in pg.execute('SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s' + where,
                                              (table, *args))]
        spent['pg_ms'] += (clock() - started) * 1000
        return found

    def put(table, found):
        started = clock()
        cols = columns[table]
        mem.executemany(f'INSERT INTO "{table}" ({",".join(cols)}) VALUES ({",".join("?" * len(cols))})',
                        [[row.get(c) for c in cols] for row in found])
        spent['insert_ms'] += (clock() - started) * 1000
        spent['rows'] += len(found)
        return found

    movers = put('us_movers', rows('us_movers'))
    put('us_briefings', rows('us_briefings'))
    if trade_date and not any(row.get('trade_date') == trade_date for row in movers):
        mem.commit()
        return mem
    for table in ('transcript_follow', 'macro_signals'):
        put(table, rows(table))
    put('job_runs', rows('job_runs', " AND row_data->>'job'='compute_briefing'"))
    if pg.execute("SELECT to_regclass('candidate_job_runs')").fetchone()[0] is not None:
        mem.executemany(f'INSERT INTO job_runs ({",".join(RUN_COLUMNS)}) VALUES ({",".join("?" * len(RUN_COLUMNS))})',
                        pg.execute(f'SELECT {",".join(RUN_COLUMNS)} FROM candidate_job_runs WHERE job=%s '
                                   'ORDER BY ran_at,created_at', ('compute_briefing',)).fetchall())
    put('market_indicators', [row for (row,) in pg.execute(
        "SELECT row_data FROM (SELECT row_data, row_number() OVER (PARTITION BY row_data->>'indicator' "
        "ORDER BY row_data->>'snapshot_date' DESC) n FROM legacy_snapshot_rows WHERE table_name='market_indicators' "
        "AND row_data->>'indicator' = ANY(%s)) s WHERE n <= %s", (_indicators(), SERIES_ROWS))])

    now = now or datetime.now(timezone.utc)
    days = [row['trade_date'] for row in movers if row.get('trade_date')]
    since = (now - timedelta(days=WINDOW_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
    day = (trade_date or (max(days) if days else since))[:10]  # the briefing day's documents (its discourse)
    after = (datetime.fromisoformat(day) + timedelta(days=1)).strftime('%Y-%m-%d')
    docs = put('raw_documents', rows('raw_documents', " AND (row_data->>'published_at' >= %s OR "
                                     "(row_data->>'published_at' >= %s AND row_data->>'published_at' < %s))",
                                     (since, day, after)))
    doc_ids = [str(row['id']) for row in docs]
    links = put('entity_links', rows('entity_links', " AND row_data->>'doc_id' = ANY(%s)", (doc_ids,)))
    put('enrichments', rows('enrichments', " AND row_data->>'doc_id' = ANY(%s)", (doc_ids,)))
    tickers = sorted({row['ticker'] for row in movers if row.get('ticker')})
    names = sorted({name for values in us_briefing._US_KR_NAMES.values() for name in values}
                   | set(us_briefing._ADR_HOME.values()))
    linked = {str(row['entity_id']) for row in links}
    followed = {str(row[0]) for row in mem.execute('SELECT entity_id FROM transcript_follow WHERE entity_id IS NOT NULL')}
    entities = put('entities', rows('entities', " AND (row_data->>'id' = ANY(%s) OR (row_data->>'type'='company' AND "
                                    "(row_data->>'name' = ANY(%s) OR upper(row_data->>'name') = ANY(%s))))",
                                    (sorted(linked | followed), names, tickers)))
    companies = sorted({str(row['id']) for row in entities if row.get('type') == 'company'} | followed)
    relations = put('entity_relations', rows('entity_relations', " AND row_data->>'narrative_id' IS NOT NULL AND "
                                             "(row_data->>'src_id' = ANY(%s) OR row_data->>'dst_id' = ANY(%s))",
                                             (companies, companies)))
    put('narratives', rows('narratives', " AND row_data->>'id' = ANY(%s)",
                           (sorted({str(row['narrative_id']) for row in relations}),)))
    news_since = (now - timedelta(days=WINDOW_DAYS + 1)).strftime('%Y-%m-%d')  # day prefix: any timestamp format
    put('us_ticker_news', rows('us_ticker_news', " AND row_data->>'ticker' = ANY(%s) AND (row_data->>'published_at' IS NULL "
                               "OR row_data->>'published_at' >= %s)", (tickers, news_since)))
    derive_owner_transcript_follow(mem, pg)
    derive_overrides(mem, pg, skip=set(OVERRIDES) - set(TABLES))
    mem.commit()
    return mem


def build_briefing(factory, trade_date=None):
    """The legacy briefing (force=False: a pure read) computed on the PG rows."""
    from pipeline import us_briefing
    from pipeline.postgres_legacy_projection import write_connection_var
    from routers.postgres_owner_legacy_fixture import _Borrowed
    started = time.perf_counter()
    spent = {}
    with factory() as pg:
        connected = time.perf_counter()
        mem = load(pg, trade_date=trade_date, spent=spent)
    loaded = time.perf_counter()
    token = write_connection_var.set(_Borrowed(mem))
    try:
        return us_briefing.build_briefing(force=False, trade_date=trade_date)
    finally:
        write_connection_var.reset(token)
        mem.close()
        done = time.perf_counter()
        # One line per request in the API log: where a slow answer spent its time (PG reads or the legacy computation).
        print('us_briefing_timing ' + json.dumps({
            'trade_date': trade_date, 'connect_ms': round((connected - started) * 1000),
            'pg_ms': round(spent.get('pg_ms', 0)), 'insert_ms': round(spent.get('insert_ms', 0)), 'rows': spent.get('rows'),
            'load_ms': round((loaded - connected) * 1000), 'compute_ms': round((done - loaded) * 1000),
            'total_ms': round((done - started) * 1000)}), flush=True)


def _base_schema(conn):
    """The snapshot schema whose legacy_snapshot_rows table the ledger view reads."""
    return conn.execute("SELECT DISTINCT n.nspname FROM pg_depend d JOIN pg_rewrite r ON r.oid=d.objid "
                        "JOIN pg_class c ON c.oid=d.refobjid JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE r.ev_class='legacy_snapshot_rows'::regclass AND c.relname='legacy_snapshot_rows' "
                        "AND c.relkind='r'").fetchone()[0]


def read_indexes(conn):
    """(schema, name, CREATE INDEX) for the briefing's three narrow reads of the ledger view (load above): documents
    by date, narrative relations by endpoint, a series' newest rows. Partial expression indexes, built CONCURRENTLY."""
    base, here = _base_schema(conn), conn.execute('SELECT current_schema()').fetchone()[0]
    found = []
    for schema, table, name, expression, kind in (
            (base, 'legacy_snapshot_rows', 'legacy_snapshot_rows_doc_published', "(row_data->>'published_at')", 'raw_documents'),
            (base, 'legacy_snapshot_rows', 'legacy_snapshot_rows_relation_src', "(row_data->>'src_id')", 'entity_relations'),
            (base, 'legacy_snapshot_rows', 'legacy_snapshot_rows_relation_dst', "(row_data->>'dst_id')", 'entity_relations'),
            (here, 'legacy_supplement_rows', 'legacy_supplement_rows_indicator_date',
             "(row_data->>'indicator'), (row_data->>'snapshot_date')", 'market_indicators')):
        found.append((schema, name, f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {schema}.{table} '
                                    f"({expression}) WHERE table_name='{kind}'"))
    return found


def has_read_indexes(conn):
    return all(conn.execute('SELECT to_regclass(%s)', (f'{schema}.{name}',)).fetchone()[0] is not None
               for schema, name, _ in read_indexes(conn))


def initialize_read_indexes(conn):
    """Needs an autocommit connection (CONCURRENTLY): the collectors keep writing while each index is built."""
    for schema, name, ddl in read_indexes(conn):
        if conn.execute('SELECT to_regclass(%s)', (f'{schema}.{name}',)).fetchone()[0] is None:
            conn.execute(ddl)


def list_briefings(pg, limit=30):
    """pipeline.us_briefing.list_briefings read straight from the ledger view: newest trade date first."""
    return [{'trade_date': day, 'model': model, 'created_at': created} for day, model, created in pg.execute(
        "SELECT row_data->>'trade_date', row_data->>'model', row_data->>'created_at' FROM legacy_snapshot_rows "
        "WHERE table_name='us_briefings' ORDER BY row_data->>'trade_date' COLLATE \"C\" DESC LIMIT %s",
        (None if limit < 0 else limit,))]  # SQLite: a negative LIMIT is no limit


def _like(pattern):
    """SQLite's LIKE: '%' and '_' wildcards, ASCII letters in any case."""
    import re
    return re.compile(''.join('.*' if c == '%' else '.' if c == '_' else re.escape(c) for c in pattern),
                      re.IGNORECASE | re.ASCII | re.DOTALL)


RECENT_DAYS = 3  # one read of every recent document; a source with nothing newer is then read on its own


def _documents(pg, extra='', args=(), days=None):
    """(source_type, source_id, published_at) of documents, from `days` ago when given."""
    where = " AND row_data->>'published_at' >= %s" if days else ''
    since = ((datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d'),) if days else ()
    return pg.execute("SELECT row_data->>'source_type', row_data->>'source_id', row_data->>'published_at' "
                      "FROM legacy_snapshot_rows WHERE table_name='raw_documents'" + extra + where, (*args, *since)).fetchall()


def _gather(rows, key_of, found=None):
    """{key: [newest published_at, [published_at...]]}; ordering is SQLite's (binary), not the database's."""
    found = {} if found is None else found
    for source_type, source_id, published in rows:
        for key in key_of(source_type, source_id):
            entry = found.setdefault(key, [None, []])
            if published is not None:
                entry[1].append(published)
                entry[0] = max(entry[0] or published, published)
    return found


def briefing_sources(pg):
    """pipeline.us_briefing.briefing_sources from the ledger view, without loading the rows into SQLite. Telegram
    channel switches are the operator's ledger over the collected rows, as the projection derives them."""
    from pipeline.macro_news import FEEDS
    from pipeline.postgres_owner_records_fixture import SOURCE_TABLES
    from pipeline.us_briefing import MACRO_CHANNELS, _MENTION_HOURS, _source_item
    from pipeline.postgres_screen_reads import prepare
    prepare(pg)
    clock = sqlite3.connect(':memory:')  # SQLite's julianday() for _source_item's ages; no rows
    clock.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc)
    day_ago = (now - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
    channels = {row['channel_name']: dict(row) for (row,) in pg.execute(
        "SELECT row_data FROM legacy_snapshot_rows WHERE table_name='telegram_channels' AND "
        "row_data->>'channel_name' = ANY(%s)", (list(MACRO_CHANNELS),))}
    table, column = SOURCE_TABLES['telegram']
    for key, data in pg.execute("SELECT key, row_data FROM owner_source_additions WHERE kind='telegram' "
                                "ORDER BY added_at, key"):
        if key in MACRO_CHANNELS and key not in channels:
            channels[key] = dict(data)
    for key, active, collect in pg.execute("SELECT key, is_active, collect_enabled FROM owner_source_settings "
                                           "WHERE kind='telegram'"):
        if key in channels:
            channels[key]['is_active'] = channels[key].get('is_active') if active is None else active
            channels[key]['collect_enabled'] = channels[key].get('collect_enabled') if collect is None else collect
    patterns = {ch: _like(ch + '/%') for ch in MACRO_CHANNELS}

    def channel(source_type, source_id):
        return [ch for ch, p in patterns.items() if source_type == 'telegram' and source_id and p.fullmatch(source_id)]
    telegram = " AND row_data->>'source_type'='telegram'"
    posts = _gather(_documents(pg, telegram, days=RECENT_DAYS), channel)
    quiet = [ch for ch in MACRO_CHANNELS if not posts.get(ch, [None])[0]]
    if quiet:  # nothing lately: those channels' own documents only, in one read (source id index, migration 18)
        for ch in quiet:
            posts.pop(ch, None)
        _gather(_documents(pg, telegram + ' AND (' + ' OR '.join(["lower(row_data->>'source_id') LIKE %s"] * len(quiet))
                           + ')', tuple(ch.lower() + '/%' for ch in quiet)), channel, posts)
    tg = []
    for ch in MACRO_CHANNELS:
        meta = channels.get(ch)
        last, seen = posts.get(ch, [None, []])
        tg.append(_source_item(clock, (meta.get('display_name') if meta else None) or ch,
                               '미등록 채널' if not meta else f'@{ch}', f'https://t.me/{ch}', last,
                               sum(p >= day_ago for p in seen),
                               enabled=bool(meta and meta.get('is_active') and meta.get('collect_enabled'))))
    feeds = {}
    for feed, published in pg.execute("SELECT row_data->>'feed', row_data->>'published_at' FROM legacy_snapshot_rows "
                                      "WHERE table_name='macro_news'"):
        if published is not None:
            entry = feeds.setdefault(feed, [None, 0])
            entry[0] = max(entry[0] or published, published)
            entry[1] += published >= day_ago
    news = [_source_item(clock, f['publisher'], f['section'], f['url'], *feeds.get(f['key'], [None, 0]))
            for f in FEEDS]

    def newest(table, column, where='', args=()):
        values = [v for (v,) in pg.execute(f"SELECT row_data->>'{column}' FROM legacy_snapshot_rows "
                                           f"WHERE table_name=%s{where}", (table, *args)) if v is not None]
        return max(values) if values else None
    mention_cut = (now - timedelta(hours=_MENTION_HOURS)).strftime('%Y-%m-%dT%H:%M:%S')
    docs = _gather(_documents(pg, days=RECENT_DAYS), lambda *_: ['all']).get('all', [None, []])
    if not docs[0]:  # nothing in the recent days: the newest of all documents
        docs = _gather(_documents(pg), lambda *_: ['all']).get('all', [None, []])
    company = [
        _source_item(clock, 'TradingView 스크리너', '전일 거래대금 상위 20 (섹터·등락률)', None,
                     newest('us_movers', 'fetched_at'), None),
        _source_item(clock, 'Yahoo Finance 종목 뉴스', '개별 이슈 종목의 헤드라인', None,
                     newest('us_ticker_news', 'fetched_at'), None),
        _source_item(clock, '수집 문서 언급', f'구독 소스 전체, 최근 {_MENTION_HOURS}시간 · 내러티브 요지', None,
                     docs[0], sum(p >= mention_cut for p in docs[1])),
    ]
    indicators = [
        _source_item(clock, '미국 지수', 'S&P 500 · 나스닥 · 다우 종가', None,
                     newest('market_indicators', 'snapshot_date', " AND row_data->>'indicator' = ANY(%s)",
                            (['index_sp500', 'index_nasdaq', 'index_dow'],)), None),
        _source_item(clock, '매크로 지표 (Yahoo·FRED)', '금리 · 달러 · 유가 · 금 · 신용 · 유동성', None,
                     newest('market_indicators', 'snapshot_date', " AND row_data->>'indicator' ILIKE 'macro_%%'"), None),
    ]
    clock.close()
    return {'groups': [
        {'key': 'macro_telegram', 'label': '텔레그램 매크로 채널', 'used_for': '매크로 문단', 'items': tg},
        {'key': 'macro_news', 'label': '미국 매체 · Fed', 'used_for': '매크로 문단', 'items': news},
        {'key': 'company', 'label': '거래대금 · 종목 재료', 'used_for': '기업 문단', 'items': company},
        {'key': 'indicators', 'label': '시장 지표', 'used_for': '시장 반응 근거', 'items': indicators},
    ]}


def source_indexes(conn):
    """The source-status read of one quiet channel's documents (briefing_sources): source id prefix, any case."""
    base = _base_schema(conn)
    return [(base, 'legacy_snapshot_rows_doc_source',
             f'CREATE INDEX CONCURRENTLY IF NOT EXISTS legacy_snapshot_rows_doc_source ON {base}.legacy_snapshot_rows '
             "(lower(row_data->>'source_id') text_pattern_ops) WHERE table_name='raw_documents'")]


def has_source_indexes(conn):
    return all(conn.execute('SELECT to_regclass(%s)', (f'{schema}.{name}',)).fetchone()[0] is not None
               for schema, name, _ in source_indexes(conn))


def initialize_source_indexes(conn):
    for schema, name, ddl in source_indexes(conn):
        if conn.execute('SELECT to_regclass(%s)', (f'{schema}.{name}',)).fetchone()[0] is None:
            conn.execute(ddl)
