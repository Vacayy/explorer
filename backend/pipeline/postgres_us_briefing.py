"""The US briefing read from PG (single-path candidate), without the projection file.

The rows the legacy briefing reads are taken from the ledger view (legacy_snapshot_rows: snapshot, supplement,
overlays, revisions) into a private in-memory SQLite file per request, with the owner's ledgers laid over them the way
the projection builder does (transcript follows, row overrides, candidate run records), and the legacy computation
(pipeline.us_briefing.build_briefing) runs on that file unchanged. Only the rows it can reach are loaded:

- whole: us_movers, us_briefings, narratives, transcript_follow, macro_signals (small tables)
  (a past day without its movers snapshot reads only the stored synthesis: nothing else is loaded)
- job_runs: the 06:30 briefing's own records (compute_briefing)
- market_indicators: the newest SERIES_ROWS rows of each series the briefing and the macro leader read
- raw_documents of the briefing day and of the mention/news windows (recent days), with their links and enrichments
- entities: the ones those documents link and the company names and tickers the movers resolve through
- entity_relations: the narrative relations of those entities
- us_ticker_news: the movers' tickers
"""
import sqlite3
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


def load(pg, now=None, trade_date=None):
    """The in-memory file the briefing reads (sqlite3.Row rows, like the projection's connections). For a past
    `trade_date` without its movers snapshot only the stored synthesis is read, so only it is loaded."""
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

    def rows(table, where='', args=()):
        return [row for (row,) in pg.execute('SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s' + where,
                                             (table, *args))]

    def put(table, found):
        cols = columns[table]
        mem.executemany(f'INSERT INTO "{table}" ({",".join(cols)}) VALUES ({",".join("?" * len(cols))})',
                        [[row.get(c) for c in cols] for row in found])
        return found

    movers = put('us_movers', rows('us_movers'))
    put('us_briefings', rows('us_briefings'))
    if trade_date and not any(row.get('trade_date') == trade_date for row in movers):
        mem.commit()
        return mem
    for table in ('narratives', 'transcript_follow', 'macro_signals'):
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
    put('entity_relations', rows('entity_relations', " AND row_data->>'narrative_id' IS NOT NULL AND "
                                 "(row_data->>'src_id' = ANY(%s) OR row_data->>'dst_id' = ANY(%s))", (companies, companies)))
    put('us_ticker_news', rows('us_ticker_news', " AND row_data->>'ticker' = ANY(%s)", (tickers,)))
    derive_owner_transcript_follow(mem, pg)
    derive_overrides(mem, pg, skip=set(OVERRIDES) - set(TABLES))
    mem.commit()
    return mem


def build_briefing(factory, trade_date=None):
    """The legacy briefing (force=False: a pure read) computed on the PG rows."""
    from pipeline import us_briefing
    from pipeline.postgres_legacy_projection import write_connection_var
    from routers.postgres_owner_legacy_fixture import _Borrowed
    with factory() as pg:
        mem = load(pg, trade_date=trade_date)
    token = write_connection_var.set(_Borrowed(mem))
    try:
        return us_briefing.build_briefing(force=False, trade_date=trade_date)
    finally:
        write_connection_var.reset(token)
        mem.close()


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
