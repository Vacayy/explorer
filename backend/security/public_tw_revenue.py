"""Read-only public projection of stored Taiwan monthly disclosures."""
from contextlib import closing
from pathlib import Path
import sqlite3
from config import DB_PATH
from pipeline.tw_revenue import read_snapshot

COLUMNS = {'code','ym','market','revenue','last_year','mom_pct','yoy_pct','note','fetched_at'}

def authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT: return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and database == 'main' and table == 'tw_monthly_revenue' and (column in COLUMNS or column == ''): return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and column == 'max': return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY

def stored_revenue(months=36, *, path=None):
    with closing(sqlite3.connect(Path(path or DB_PATH).resolve().as_uri()+'?mode=ro',uri=True,timeout=3)) as conn:
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN');conn.set_authorizer(authorize)
        return read_snapshot(conn, months)
