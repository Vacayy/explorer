"""Screen API error log (routers.spine_client_errors) on the candidate PG schema.

The frontend reports contract violations, 5xx, timeouts and network errors; one row per API, kind, status and
field keeps a count and the first and last time (same rule as the legacy SQLite writer). The legacy readers
(the client-errors list, admin observe, the health check) see it through a per-connection TEMP copy, not the
projection file: a report is not a reason to rebuild the projection.
"""
import hashlib
import json

from pipeline.postgres_graph_fixture import _guard

COLUMNS = ('signature', 'endpoint', 'kind', 'status', 'field', 'detail', 'issues_json', 'page', 'count', 'first_seen', 'last_seen')
NOW = "to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS')"


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        conn.execute('CREATE TABLE IF NOT EXISTS client_errors (signature TEXT PRIMARY KEY,endpoint TEXT NOT NULL,kind TEXT NOT NULL,'
                     'status INTEGER,field TEXT,detail TEXT,issues_json TEXT,page TEXT,count INTEGER DEFAULT 1,'
                     'first_seen TEXT,last_seen TEXT)')


def ready(conn):
    return conn.execute("SELECT to_regclass('client_errors')").fetchone()[0] is not None


def record(conn, body):
    sig = hashlib.sha1(f"{body.endpoint}|{body.kind}|{body.status}|{body.field}".encode()).hexdigest()[:16]
    conn.execute(f'INSERT INTO client_errors ({",".join(COLUMNS)}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,{NOW},{NOW}) '
                 'ON CONFLICT (signature) DO UPDATE SET count=client_errors.count+1,last_seen=excluded.last_seen,'
                 'detail=excluded.detail,issues_json=excluded.issues_json,page=excluded.page',
                 (sig, body.endpoint, body.kind, body.status, body.field, body.detail,
                  json.dumps(body.issues, ensure_ascii=False, default=str)[:4000], body.page))


def derive(conn, pg):
    """TEMP client_errors for one legacy read connection (the legacy DDL), filled from PG."""
    if not ready(pg):
        return
    conn.execute('CREATE TEMP TABLE IF NOT EXISTS client_errors (signature TEXT PRIMARY KEY, endpoint TEXT NOT NULL, kind TEXT NOT NULL, '
                 'status INTEGER, field TEXT, detail TEXT, issues_json TEXT, page TEXT, count INTEGER DEFAULT 1, first_seen TEXT, last_seen TEXT)')
    conn.execute('DELETE FROM temp.client_errors')
    conn.executemany(f'INSERT INTO temp.client_errors ({",".join(COLUMNS)}) VALUES ({",".join("?" for _ in COLUMNS)})',
                     pg.execute(f'SELECT {",".join(COLUMNS)} FROM client_errors').fetchall())
