"""Public market probabilities, with no operator pins or request-time collection."""
from contextlib import closing
from pathlib import Path
import sqlite3
from config import DB_PATH
from pipeline.kalshi import read_latest, detail

COLUMNS = {
    'kalshi_events': {'fetched_at','rank','category','series_ticker','event_ticker','title','subtitle','recent_volume','close_ts','outcomes_json'},
    'kalshi_candles': {'market_ticker','day','price'},
    'kalshi_event_cache': {'event_ticker','body_json','fetched_at'},
}


def authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT: return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and database == 'main' and column in COLUMNS.get(table,set()): return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and column in {'max','datetime','date'}: return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def connection(path=None):
    conn=sqlite3.connect(Path(path or DB_PATH).resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN');conn.set_authorizer(authorize)
    return conn


def predictions(*,path=None):
    with closing(connection(path)) as conn:return read_latest(conn,include_pins=False)


def prediction_detail(event_ticker,range_='3m',*,path=None):
    with closing(connection(path)) as conn:return detail(event_ticker,range_,conn=conn,stored_only=True)
