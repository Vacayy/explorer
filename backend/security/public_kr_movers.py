"""Stored KR market ranking; private document evidence is not yet public-linked."""
from contextlib import closing
from pathlib import Path
import sqlite3

from config import DB_PATH
from models.kr import KrMovers
from pipeline.kr_movers import _read_snapshot, _result

COLUMNS = {'trade_date', 'rank', 'stock_code', 'name', 'market', 'close', 'volume',
           'value_traded', 'change_pct', 'sector', 'market_cap', 'is_new', 'fetched_at'}


def authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT: return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and database == 'main' and table == 'kr_movers' and column in COLUMNS:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and column == 'max': return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def connection(path=None):
    conn = sqlite3.connect(Path(path or DB_PATH).resolve().as_uri()+'?mode=ro', uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    conn.execute('BEGIN')
    conn.set_authorizer(authorize)
    return conn


def stored_movers(*, path=None):
    with closing(connection(path)) as conn:
        return KrMovers(**_result('ok', _read_snapshot(conn), None, include_evidence=False))
