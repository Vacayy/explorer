"""Isolated collection runs: each run's results are kept apart and only verified rows are published, by key, in one
PostgreSQL transaction with the run record and the per-source state (agent-whiteboard single-data-path.md,
'실행별 결과 격리와 게시', 2026-11-21).

The shared collector file (/trial/work.db) is not used by these jobs. A run seeds a private SQLite file with the rows
of the tables it owns from the PG supplement (the authoritative copy), runs the unchanged collectors against it,
and publishes the difference between the seed and the result: changed or new rows by natural key, removed keys
deleted. Rows a run did not touch are never rewritten, so a stale seed cannot overwrite newer rows.

collect_source_state keeps, per job and source, the last outcome, since when it fails and what is missing, so a
later run (after a restart or on another day) knows where to fill from.
"""
import itertools
import json

from psycopg.types.json import Jsonb

from pipeline import postgres_collect_runs, postgres_live_tables
from pipeline.postgres_graph_fixture import _guard

# Natural keys of the tables the isolated jobs own (the same keys as postgres_supplement_preserve).
KEYS = {'ext_series': ('series', 'period'),
        'expectation_claims': ('source', 'url', 'node_key', 'subject', 'metric', 'target_period'),
        'sector_benchmark_prices': ('ticker', 'trade_date'),
        'sector_index': ('sector', 'trade_date'),
        'us_ticker_sectors': ('ticker',),
        'stock_prices': ('stock_code', 'trade_date'),
        'credit_bonds': ('ticker',), 'credit_quotes': ('symbol', 'date'), 'treasury_curve': ('date', 'tenor'),
        'retail_flows': ('date',), 'retail_snapshots': ('episode',), 'tw_monthly_revenue': ('code', 'ym')}
# Job records of isolated runs take their own id band, apart from the shared collector file's (100,000,000 on), so
# the two paths never hand out the same id.
JOB_RUNS_BAND = 150_000_000
# A large table is seeded and compared only from a start date on this column (the run passes the date).
WINDOWS = {'stock_prices': 'trade_date'}
NOW = postgres_collect_runs.NOW


def initialize(pg):
    _guard(pg)
    with pg.transaction():
        pg.execute('CREATE TABLE IF NOT EXISTS collect_source_state (job TEXT NOT NULL,source TEXT NOT NULL,'
                   'status TEXT NOT NULL,last_ok_at TEXT,failing_since TEXT,last_error TEXT,'
                   'attempts INTEGER NOT NULL DEFAULT 0,gaps_json TEXT NOT NULL DEFAULT \'[]\','
                   f'updated_at TEXT NOT NULL DEFAULT {NOW},PRIMARY KEY (job,source))')


def states(pg, job):
    """{source: {status, last_ok_at, failing_since, last_error, attempts, gaps}} of a job."""
    return {source: {'status': status, 'last_ok_at': ok_at, 'failing_since': since, 'last_error': error,
                     'attempts': attempts, 'gaps': json.loads(gaps)}
            for source, status, ok_at, since, error, attempts, gaps in pg.execute(
                'SELECT source,status,last_ok_at,failing_since,last_error,attempts,gaps_json FROM collect_source_state '
                'WHERE job=%s', (job,))}


def seed(pg, conn, tables, since=None):
    """Create `tables` in the private SQLite `conn` with their PG supplement rows (a WINDOWS table from `since`);
    returns {table: row count}. An id table continues after the highest id in all of PG, not only in the window."""
    counts = {}
    for table in tables:
        if table not in KEYS:
            raise ValueError(f'{table} is not owned by an isolated job')
        found = pg.execute('SELECT columns,schema_sql FROM legacy_supplement_tables WHERE table_name=%s', (table,)).fetchone()
        if found is None:
            raise ValueError(f'{table} is not a supplement table')
        columns, schema_sql = found
        conn.execute(schema_sql)
        marks = ','.join('?' * len(columns))
        window = f" AND row_data->>'{WINDOWS[table]}' >= %s" if table in WINDOWS else ''
        if window and not since:
            raise ValueError(f'{table} is seeded from a start date')
        rows = pg.execute('SELECT row_data FROM legacy_supplement_rows WHERE table_name=%s' + window + ' ORDER BY row_ordinal',
                          (table, since) if window else (table,))
        conn.executemany(f'INSERT INTO "{table}" ({",".join(columns)}) VALUES ({marks})',
                         ([row.get(column) for column in columns] for (row,) in rows))
        if window and 'id' in columns:
            top = pg.execute("SELECT COALESCE(max((row_data->>'id')::bigint),0) FROM legacy_supplement_rows WHERE table_name=%s",
                             (table,)).fetchone()[0]
            conn.execute('DELETE FROM sqlite_sequence WHERE name=?', (table,))
            conn.execute('INSERT INTO sqlite_sequence (name, seq) VALUES (?,?)', (table, top))
        counts[table] = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    conn.commit()
    return counts


def seed_job_runs(pg, conn):
    """An empty job_runs in the private file whose ids continue in the isolated band."""
    schema_sql = pg.execute("SELECT schema_sql FROM legacy_supplement_tables WHERE table_name='job_runs'").fetchone()[0]
    conn.execute(schema_sql)
    top = pg.execute("SELECT COALESCE(max((row_data->>'id')::bigint),0) FROM legacy_supplement_rows WHERE table_name='job_runs' "
                     "AND (row_data->>'id')::bigint >= %s", (JOB_RUNS_BAND,)).fetchone()[0]
    conn.execute('DELETE FROM sqlite_sequence WHERE name=?', ('job_runs',))
    conn.execute('INSERT INTO sqlite_sequence (name, seq) VALUES (?,?)', ('job_runs', max(top, JOB_RUNS_BAND - 1)))
    conn.commit()


def rows_by_key(conn, table):
    """{natural key: row dict} of a table in the private SQLite file."""
    cursor = conn.execute(f'SELECT * FROM "{table}"')
    names = [d[0] for d in cursor.description]
    key = KEYS[table]
    out = {}
    for values in cursor:
        row = dict(zip(names, values))
        out[tuple(row[c] for c in key)] = row
    return out


def delta(before, after):
    """(rows to upsert, keys to delete) between two rows_by_key maps."""
    return [row for k, row in after.items() if before.get(k) != row], [k for k in before if k not in after]


_KEY_TABLES = itertools.count()


def _text(key):
    return tuple(None if v is None else str(v) for v in key)


def _ordinals(pg, table, keys, key_columns=None):
    """{key as text: row ordinal} of the PG rows with these keys (one pass over the table, not a full load)."""
    if not keys:
        return {}
    name = f'isolated_keys_{next(_KEY_TABLES)}'  # one per call: a transaction may look up the same table twice
    pg.execute(f'CREATE TEMP TABLE {name} (k TEXT[]) ON COMMIT DROP')
    with pg.cursor().copy(f'COPY {name} (k) FROM STDIN') as copy:
        for k in keys:
            copy.write_row((list(_text(k)),))
    expr = 'ARRAY[' + ','.join(f"r.row_data->>'{c}'" for c in (key_columns or KEYS[table])) + ']'
    return {tuple(k): ordinal for ordinal, k in pg.execute(
        f'SELECT r.row_ordinal, {expr} FROM legacy_supplement_rows r JOIN {name} i ON i.k = {expr} '
        'WHERE r.table_name=%s', (table,))}


def apply_keyed(pg, table, key, rows, deleted=(), *, live=None):
    """In the caller's transaction: upsert `rows` and delete `deleted` keys of a supplement table by `key`.
    Returns (rows upserted, rows deleted)."""
    if live is None:
        live = postgres_live_tables.ready(pg)
    pg.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('supplement:' + table,))
    if live:
        postgres_live_tables.mark(pg, table)
    ordinals = _ordinals(pg, table, [tuple(row[c] for c in key) for row in rows] + list(deleted), key)
    last = pg.execute('SELECT COALESCE(max(row_ordinal),-1) FROM legacy_supplement_rows WHERE table_name=%s',
                      (table,)).fetchone()[0]
    for row in rows:
        ordinal = ordinals.get(_text(tuple(row[c] for c in key)))
        if ordinal is None:
            last += 1
            pg.execute('INSERT INTO legacy_supplement_rows (table_name,row_ordinal,row_data) VALUES (%s,%s,%s)',
                       (table, last, Jsonb(row)))
        else:
            pg.execute('UPDATE legacy_supplement_rows SET row_data=%s WHERE table_name=%s AND row_ordinal=%s',
                       (Jsonb(row), table, ordinal))
    gone = [ordinals[_text(k)] for k in deleted if _text(k) in ordinals]
    if gone:
        pg.execute('DELETE FROM legacy_supplement_rows WHERE table_name=%s AND row_ordinal=ANY(%s)', (table, gone))
    pg.execute('UPDATE legacy_supplement_tables SET row_count=(SELECT count(*) FROM legacy_supplement_rows '
               'WHERE table_name=%s) WHERE table_name=%s', (table, table))
    return len(rows), len(gone)


def publish(pg, label, started, outcome, changes, source_states, *, token, requests=None, result=None, records=()):
    """One transaction: every table's upserts/deletes by key, the per-source state and the run record.
    `changes` = {table: (rows, deleted keys)}. Returns (run id, {table: (upserted, deleted)})."""
    applied = {}
    with pg.transaction():
        live = postgres_live_tables.ready(pg)
        for table, (rows, deleted) in changes.items():
            if rows or deleted:
                applied[table] = apply_keyed(pg, table, KEYS[table], rows, deleted, live=live)
        if records:  # the run's own job records (the legacy script's), in the isolated id band
            applied['job_runs'] = apply_keyed(pg, 'job_runs', ('id',), list(records), live=live)
        for source, state in source_states.items():
            pg.execute('INSERT INTO collect_source_state (job,source,status,last_ok_at,failing_since,last_error,attempts,'
                       f'gaps_json,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,{NOW}) ON CONFLICT (job,source) DO UPDATE SET '
                       'status=excluded.status,last_ok_at=excluded.last_ok_at,failing_since=excluded.failing_since,'
                       'last_error=excluded.last_error,attempts=excluded.attempts,gaps_json=excluded.gaps_json,'
                       'updated_at=excluded.updated_at',
                       (label, source, state['status'], state.get('last_ok_at'), state.get('failing_since'),
                        (state.get('last_error') or '')[:300] or None, state.get('attempts', 0),
                        json.dumps(state.get('gaps') or [], ensure_ascii=False)))
        run_id = postgres_collect_runs.record(pg, label, started, outcome, requests=requests,
                                              # the token first: the stored result is cut at 4000 characters
                                              result={'token': token,
                                                      'applied': {t: list(n) for t, n in applied.items()},
                                                      **(result or {})})
    return run_id, applied


def published(pg, label, token):
    """The run id recorded with `token`, or None: whether a publication whose commit was interrupted took effect."""
    found = pg.execute("SELECT id FROM collect_runs WHERE label=%s AND result_json LIKE %s ORDER BY id DESC LIMIT 1",
                       (label, f'%"token": "{token}"%')).fetchone()
    return found[0] if found else None
