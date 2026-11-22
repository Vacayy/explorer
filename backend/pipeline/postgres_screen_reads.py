"""Screen reads from PG without the projection file (D-294): the rows a legacy read reaches, taken from the ledger view
into a private in-memory SQLite file per request, and the legacy function run on it unchanged.

Each screen names its loads (SCREENS); `answer` runs one and logs `screen_timing` (PG reads, filling the file, the
legacy computation). The first screens are the home market summary's, which read only the market tables the isolated
jobs publish by key:

  indices       market_indicators: every row of the index series (their whole history and fetch times);
                index_intraday (the latest bar while a market is open)
  macro         market_indicators: the newest SERIES_ROWS of the macro leader's series; macro_signals
  regime        market_indicators: the newest SERIES_ROWS of the regime's series
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


SCREENS = {
    'indices': (('market_indicators', 'index_intraday'),
                lambda rows: (rows.series(_index_series()), rows.table('index_intraday'))),
    'macro': (('market_indicators', 'macro_signals'),
              lambda rows: (rows.series(_macro_series(), SERIES_ROWS), rows.table('macro_signals'))),
    'regime': (('market_indicators',), lambda rows: rows.series(_regime_series(), SERIES_ROWS)),
    'market_today': (('market_today', 'market_today_links', 'narrative_candidates'),
                     lambda rows: [rows.table(t) for t in ('market_today', 'market_today_links', 'narrative_candidates')]),
}


def answer(factory, screen, compute):
    """`compute()` (a legacy read) on the screen's rows from PG; one `screen_timing` line per request."""
    from pipeline.postgres_legacy_projection import write_connection_var
    from routers.postgres_owner_legacy_fixture import _Borrowed
    tables, load = SCREENS[screen]
    started = time.perf_counter()
    with factory() as pg:
        pg.execute('SET jit = off')  # a new connection per request: JIT would compile every view query again (D-294)
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
