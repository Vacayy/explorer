"""Public corporate disclosures, excluding personal group labels and job logs."""
from contextlib import closing
from pathlib import Path
import os
import sqlite3
from routers.spine_actions import ACTION_COLUMNS, RIGHTS_COLUMNS, read_actions, read_rights

DB_PATH = os.environ.get('EXPLORER_PUBLIC_KR_SEASON_DB')
COLUMNS = {'corporate_actions': set(ACTION_COLUMNS), 'capital_raise_details': set(RIGHTS_COLUMNS),
           'stock_prices': {'stock_code', 'trade_date', 'close'}, 'public_actions_metadata': {'as_of'}}


def authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT: return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and table in COLUMNS:
        if database == 'main' and column in COLUMNS[table]: return sqlite3.SQLITE_OK
        if database in ('main', None) and column == '': return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and column in {'count','sum','coalesce','like','max'}: return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def connection(path=None):
    if not (path or DB_PATH): raise sqlite3.OperationalError('Public corporate actions snapshot unavailable')
    conn=sqlite3.connect(Path(path or DB_PATH).resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN');conn.set_authorizer(authorize)
    return conn


def scanned_at(conn):
    row=conn.execute('SELECT as_of FROM public_actions_metadata LIMIT 1').fetchone()
    return row['as_of'] if row else None


def actions(type=None, days=30, kind='all', stock_code=None, *, path=None):
    with closing(connection(path)) as conn:
        return read_actions(conn,type,days,kind,stock_code,mine={},as_of=scanned_at(conn))


def rights(*, path=None):
    with closing(connection(path)) as conn:
        return read_rights(conn,mine={},as_of=scanned_at(conn))
