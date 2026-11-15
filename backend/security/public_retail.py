"""Market-wide retail statistics, excluding collector configuration and writes."""
from contextlib import closing
from pathlib import Path
import sqlite3
from config import DB_PATH
from pipeline import retail_heat as rh

COLUMNS = {'retail_flows': set(rh.FLOW_COLUMNS), 'retail_snapshots': {'episode','date','metrics_json'}}


def authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT: return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and database == 'main' and column in COLUMNS.get(table, set()):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def connection(path=None):
    conn=sqlite3.connect(Path(path or DB_PATH).resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN');conn.set_authorizer(authorize)
    return conn


def summary(*, path=None):
    with closing(connection(path)) as conn: return rh.read_summary(conn)


def history(days=1500, *, path=None):
    with closing(connection(path)) as conn: return {'points':rh.read_history(conn,days)}


def snapshots(*, path=None):
    with closing(connection(path)) as conn: return rh.read_snapshots(conn)
