"""Screen reads from PG without the projection file (D-294): the rows a legacy read reaches, taken from the ledger view
into a private in-memory SQLite file per request, and the legacy function run on it unchanged.

Each screen names its loads (SCREENS); `answer` runs one and logs `screen_timing` (PG reads, filling the file, the
legacy computation). The first screens are the home market summary's, which read only the market tables the isolated
jobs publish by key:

  indices       market_indicators: every row of the index series (their whole history and fetch times);
                index_intraday (the latest bar while a market is open)
  macro         market_indicators: the newest SERIES_ROWS of the macro leader's series; macro_signals
  regime        market_indicators: the newest SERIES_ROWS of the regime's series
  kr_overview   market_indicators: the newest rows of the KR index and USD/KRW series; index_intraday; retail_flows;
                the market breadth computed in PG (kr_breadth) into the legacy read's own 10-minute memo
  us_overview   market_indicators: the newest rows of the US index series and the four US tiles'; index_intraday
  market_today  market_today, market_today_links, narrative_candidates (small tables); the API's market-today route
                already reads PG through pipeline.postgres_market_today_fixture
"""
import json
import sqlite3
import time

SERIES_ROWS = 100  # the newest rows of a series: these screens read at most 70


class Rows:
    """The in-memory file being filled from one PG connection."""

    def __init__(self, pg, tables):
        self.pg, self.spent = pg, {'pg_ms': 0.0, 'insert_ms': 0.0, 'rows': 0}
        self.mem = sqlite3.connect(':memory:', check_same_thread=False)
        self.mem.row_factory = sqlite3.Row
        for _name, ddl in pg.execute('SELECT table_name, schema_sql FROM legacy_snapshot_tables WHERE table_name = ANY(%s)',
                                     (list(tables),)):
            self.mem.execute(ddl)
        self.columns = {table: [row[1] for row in self.mem.execute(f'PRAGMA table_info("{table}")')] for table in tables}

    def fetch(self, sql, args=()):
        started = time.perf_counter()
        found = [row for (row,) in self.pg.execute(sql, args)]
        self.spent['pg_ms'] += (time.perf_counter() - started) * 1000
        return found

    def put(self, table, found):
        started = time.perf_counter()
        cols = self.columns[table]
        self.mem.executemany(f'INSERT INTO "{table}" ({",".join(cols)}) VALUES ({",".join("?" * len(cols))})',
                             [[row.get(c) for c in cols] for row in found])
        self.spent['insert_ms'] += (time.perf_counter() - started) * 1000
        self.spent['rows'] += len(found)
        return found

    def table(self, table, where='', args=()):
        return self.put(table, self.fetch('SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s' + where,
                                          (table, *args)))

    def series(self, indicators, newest=None):
        """market_indicators rows of `indicators`: all of them, or each series' `newest` (index of migration 17)."""
        if newest is None:
            return self.table('market_indicators', " AND row_data->>'indicator' = ANY(%s)", (list(indicators),))
        return self.put('market_indicators', self.fetch(
            "SELECT row_data FROM (SELECT row_data, row_number() OVER (PARTITION BY row_data->>'indicator' "
            "ORDER BY row_data->>'snapshot_date' DESC) n FROM legacy_snapshot_rows WHERE table_name='market_indicators' "
            "AND row_data->>'indicator' = ANY(%s)) s WHERE n <= %s", (list(indicators), newest)))


def _index_series():
    from pipeline import indices
    return [indices._indicator(key) for key, *_ in indices.INDICES]


def _macro_series():
    from pipeline import indicator_canon, macro
    return sorted({f'macro_{name}' for name in [*macro.YF, *macro.FRED]}
                  | {indicator_canon.CANONICAL[name] for name in macro.CANON_RATES})


def _regime_series():
    from pipeline import indicator_canon, market_regime
    return sorted({indicator_canon.CANONICAL.get(name, name) for name in (*market_regime.RAW_INDICATORS, 'kospi_vol')})


OVERVIEW_ROWS = 300  # the KR overview reads at most 255 rows of an index series


def kr_breadth(pg):
    """pipeline.indices.kr_breadth computed in PG (the recent days of every listed price, which no in-memory file
    should hold): days within 20 of the newest, the newest two days with at least half the most prices, up/down/flat
    between them. Dates compare as SQLite's text does; closes as SQLite's REAL."""
    from datetime import date, datetime, timedelta, timezone
    # Only these reads tell the planner that random reads are cheap: at the default 4 it scans the 2.4 GB supplement
    # table instead of the price date index (5.5 s against 0.02 s); the briefing's reads got slower with it (1.5 s).
    pg.execute('SET random_page_cost = 1.1')
    try:
        return _kr_breadth(pg, date, datetime, timedelta, timezone)
    finally:
        pg.execute('RESET random_page_cost')


def _kr_breadth(pg, date, datetime, timedelta, timezone):
    recent = (datetime.now(timezone.utc) - timedelta(days=60)).strftime('%Y-%m-%d')
    newest = None
    for since in (recent, None):  # the price date index (migration 19); the whole table only if nothing is recent
        newest = pg.execute("SELECT max(row_data->>'trade_date' COLLATE \"C\") FROM legacy_snapshot_rows WHERE "
                            "table_name='stock_prices'" + (" AND row_data->>'trade_date' >= %s" if since else ''),
                            (since,) if since else ()).fetchone()[0]
        if newest:
            break
    if not newest:
        return None
    since = (date.fromisoformat(newest[:10]) - timedelta(days=20)).isoformat()
    counts = sorted(pg.execute("SELECT row_data->>'trade_date', count(*) FROM legacy_snapshot_rows WHERE "
                               "table_name='stock_prices' AND row_data->>'trade_date' >= %s GROUP BY 1", (since,)).fetchall(),
                    reverse=True)
    full = max(n for _, n in counts)
    days = [day for day, n in counts if n * 2 >= full]
    if len(days) < 2:
        return None
    day, prev = days[0], days[1]
    up, down, flat = pg.execute(
        "SELECT COALESCE(sum((a.c > b.c)::int), 0), COALESCE(sum((a.c < b.c)::int), 0), COALESCE(sum((a.c = b.c)::int), 0) "
        "FROM (SELECT row_data->>'stock_code' k, (row_data->>'close')::float8 c FROM legacy_snapshot_rows "
        "      WHERE table_name='stock_prices' AND row_data->>'trade_date' = %s) a "
        "JOIN (SELECT row_data->>'stock_code' k, (row_data->>'close')::float8 c FROM legacy_snapshot_rows "
        "      WHERE table_name='stock_prices' AND row_data->>'trade_date' = %s) b ON b.k = a.k "
        "WHERE a.c > 0 AND b.c > 0", (day, prev)).fetchone()
    if up + down == 0:
        return None
    return {'trade_date': day, 'prev_date': prev, 'up': up, 'down': down, 'flat': flat,
            'up_ratio': round(up / (up + down), 4)}


def _kr_overview(rows):
    from pipeline import market_overview
    rows.series(['index_kospi', 'index_kosdaq', 'macro_usdkrw'], OVERVIEW_ROWS)
    rows.table('index_intraday')
    rows.table('retail_flows')
    memo = market_overview._breadth_memo  # the legacy read keeps the breadth 10 minutes; it is refilled from PG
    if not (memo and time.monotonic() - memo[0] < market_overview.BREADTH_TTL):
        started = time.perf_counter()
        market_overview._breadth_memo = (time.monotonic(), kr_breadth(rows.pg))
        rows.spent['pg_ms'] += (time.perf_counter() - started) * 1000


SCREENS = {
    'indices': (('market_indicators', 'index_intraday'),
                lambda rows: (rows.series(_index_series()), rows.table('index_intraday'))),
    'macro': (('market_indicators', 'macro_signals'),
              lambda rows: (rows.series(_macro_series(), SERIES_ROWS), rows.table('macro_signals'))),
    'regime': (('market_indicators',), lambda rows: rows.series(_regime_series(), SERIES_ROWS)),
    'kr_overview': (('market_indicators', 'index_intraday', 'retail_flows'), _kr_overview),
    'us_overview': (('market_indicators', 'index_intraday'),
                    lambda rows: (rows.series(['index_sp500', 'index_nasdaq', 'index_dow', 'risk_fear_greed', 'risk_us10y',
                                               'risk_us2y', 'macro_dxy', 'macro_oil'], OVERVIEW_ROWS),
                                  rows.table('index_intraday'))),
    'market_today': (('market_today', 'market_today_links', 'narrative_candidates'),
                     lambda rows: [rows.table(t) for t in ('market_today', 'market_today_links', 'narrative_candidates')]),
}


def prepare(pg):
    """A screen read's own connection: no JIT (a new connection per request would compile every view query again).
    A session setting only; the database's stay as they are (D-294)."""
    pg.execute('SET jit = off')


def answer(factory, screen, compute):
    """`compute()` (a legacy read) on the screen's rows from PG; one `screen_timing` line per request."""
    from pipeline.postgres_legacy_projection import write_connection_var
    from routers.postgres_owner_legacy_fixture import _Borrowed
    tables, load = SCREENS[screen]
    started = time.perf_counter()
    with factory() as pg:
        prepare(pg)
        rows = Rows(pg, tables)
        load(rows)
        rows.mem.commit()
    loaded = time.perf_counter()
    token = write_connection_var.set(_Borrowed(rows.mem))
    try:
        return compute()
    finally:
        write_connection_var.reset(token)
        rows.mem.close()
        done = time.perf_counter()
        print('screen_timing ' + json.dumps({
            'screen': screen, 'pg_ms': round(rows.spent['pg_ms']), 'insert_ms': round(rows.spent['insert_ms']),
            'rows': rows.spent['rows'], 'load_ms': round((loaded - started) * 1000),
            'compute_ms': round((done - loaded) * 1000), 'total_ms': round((done - started) * 1000)}), flush=True)


def price_indexes(conn):
    """stock_prices by trade date in both the snapshot and the supplement rows: the market breadth's recent days and
    the prices job's day reads (without them three weeks of prices took 52 s)."""
    from pipeline.postgres_us_briefing import _base_schema
    base, here = _base_schema(conn), conn.execute('SELECT current_schema()').fetchone()[0]
    return [(schema, name, f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {schema}.{table} '
                           "((row_data->>'trade_date')) WHERE table_name='stock_prices'")
            for schema, table, name in ((base, 'legacy_snapshot_rows', 'legacy_snapshot_rows_price_date'),
                                        (here, 'legacy_supplement_rows', 'legacy_supplement_rows_price_date'))]


def has_price_indexes(conn):
    return all(conn.execute('SELECT to_regclass(%s)', (f'{schema}.{name}',)).fetchone()[0] is not None
               for schema, name, _ in price_indexes(conn))


def initialize_price_indexes(conn):
    for schema, name, ddl in price_indexes(conn):
        if conn.execute('SELECT to_regclass(%s)', (f'{schema}.{name}',)).fetchone()[0] is None:
            conn.execute(ddl)
