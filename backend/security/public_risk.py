"""Stored market-risk inputs, separate from personal risk/checklist records."""
from contextlib import closing
from pathlib import Path
import sqlite3
from config import DB_PATH
from pipeline.risk import read_risk, window

COLUMNS = {
    'market_indicators': {'snapshot_date','indicator','value','extra_json'},
    'credit_bonds': {'ticker','symbol','description','maturity','rating_sp','rating_moodys','source'},
    'credit_quotes': {'symbol','date','ytm'},
    'treasury_curve': {'date','tenor','yield'},
}


def authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT: return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and database == 'main' and column in COLUMNS.get(table,set()):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def risk_connection(path=None):
    conn = sqlite3.connect(Path(path or DB_PATH).resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
    conn.set_authorizer(authorize)
    return conn


def stored_risk(span=None, keys=None, *, path=None, now=None):
    with closing(risk_connection(path)) as conn:
        data = read_risk(conn,now,span,keys)
    # Keep quality/signal derived from success/failure, never collector exception text.
    for item in data['items']:
        item['error'] = '저장 지표 갱신 실패' if item.get('error') else None
        item['attempted_at'] = None
    return window(data,span,keys) if span or keys else data
