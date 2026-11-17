"""Collection freshness without a projection rebuild per collection run (architect #3 6938872502, PM 6938809334).

Collected (supplement) tables used to bump the projection version like every other change, so each collection run
rebuilt the whole projection file (index_intraday alone every 10 minutes). Now:
- Small, frequently collected tables (LIVE_TABLES) bump only `live_version`: every legacy read connection fills its
  TEMP copy of them from PG (rows cached in-process per live version), so they show from the next request, as fresh
  as the collector, without a rebuild.
- Other collected tables bump `collection_version`: the builder folds them into a rebuild at most every
  COLLECTION_BUILD_SECONDS (pipeline.postgres_legacy_projection_builder); user writes and computations still bump
  the projection version and rebuild at once.
"""
import json
import re
import threading

from pipeline.postgres_graph_fixture import _guard

LIVE_TABLES = ('index_intraday', 'kalshi_candles', 'kalshi_events', 'kalshi_event_cache')
_cache = {'version': None, 'rows': {}}
_lock = threading.Lock()


def initialize(conn):
    """Separate counters for collected tables; their refresh no longer bumps the projection version."""
    _guard(conn)
    with conn.transaction():
        for name in ('live_version', 'collection_version'):
            conn.execute(f'CREATE TABLE IF NOT EXISTS {name} (singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK (singleton),'
                         'counter BIGINT NOT NULL DEFAULT 0)')
            conn.execute(f'INSERT INTO {name} (singleton) VALUES (true) ON CONFLICT DO NOTHING')
        conn.execute("CREATE OR REPLACE FUNCTION collection_bump() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN "
                     "IF current_setting('explorer.live_refresh', true) = 'on' THEN "
                     "UPDATE live_version SET counter=counter+1; ELSE UPDATE collection_version SET counter=counter+1; "
                     "END IF; RETURN NULL; END$$")
        schema = conn.execute('SELECT current_schema()').fetchone()[0]
        # The function runs with the caller's search_path, as the triggers' other functions here are schema-qualified.
        conn.execute(f'ALTER FUNCTION collection_bump() SET search_path = "{schema}"')
        for table in ('legacy_supplement_rows', 'legacy_supplement_tables'):
            conn.execute(f'DROP TRIGGER IF EXISTS legacy_projection_bump ON {table}')
            conn.execute(f'DROP TRIGGER IF EXISTS collection_bump ON {table}')
            conn.execute(f'CREATE TRIGGER collection_bump AFTER INSERT OR DELETE OR UPDATE OR TRUNCATE ON {table} '
                         'FOR EACH STATEMENT EXECUTE FUNCTION collection_bump()')


def ready(pg):
    return pg.execute("SELECT to_regclass('live_version')").fetchone()[0] is not None


def mark(pg, table):
    """Before refreshing `table` in the caller's transaction: which counter its statements bump."""
    pg.execute("SELECT set_config('explorer.live_refresh', %s, true)", ('on' if table in LIVE_TABLES else 'off',))


def versions(pg):
    """(live, collection) counters, or (None, None) before the migration."""
    if not ready(pg):
        return None, None
    return (pg.execute('SELECT counter FROM live_version').fetchone()[0],
            pg.execute('SELECT counter FROM collection_version').fetchone()[0])


def _rows(pg, version):
    with _lock:
        if _cache['version'] == version:
            return _cache['rows']
    rows = {}
    for table in LIVE_TABLES:
        rows[table] = [data for (data,) in pg.execute(
            'SELECT row_data FROM legacy_supplement_rows WHERE table_name=%s ORDER BY row_ordinal', (table,))]
    with _lock:
        _cache.update(version=version, rows=rows)
    return rows


def derive(conn, pg):
    """TEMP copies of the live tables for one legacy read connection, filled from PG (the projection's may be older)."""
    live, _collection = versions(pg)
    if live is None:
        return None
    for table, rows in _rows(pg, live).items():
        columns = [row[1] for row in conn.execute(f'PRAGMA main.table_info("{table}")')]
        if not columns:
            continue
        if conn.execute("SELECT 1 FROM temp.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is None:
            conn.execute(f'CREATE TEMP TABLE "{table}" AS SELECT * FROM main."{table}" WHERE 0')
            # Same index names, so legacy `CREATE INDEX IF NOT EXISTS` stays a no-op under query_only (as _shadow).
            for (sql,) in conn.execute("SELECT sql FROM main.sqlite_master WHERE type='index' AND tbl_name=? "
                                       "AND sql IS NOT NULL", (table,)).fetchall():
                conn.execute(re.sub(r'^CREATE\s+(UNIQUE\s+)?INDEX\s+(IF\s+NOT\s+EXISTS\s+)?',
                                    r'CREATE \1INDEX IF NOT EXISTS temp.', sql, flags=re.I))
        conn.execute(f'DELETE FROM temp."{table}"')
        conn.executemany(f'INSERT INTO temp."{table}" ({",".join(columns)}) VALUES ({",".join("?" * len(columns))})',
                         [[row.get(column) if isinstance(row, dict) else json.loads(row).get(column) for column in columns]
                          for row in rows])
    return live
