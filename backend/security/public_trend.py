"""Original trend calculations on the prepared public KR market snapshot."""
from contextlib import closing
from functools import lru_cache
from pathlib import Path
import os
import sqlite3
from pipeline.trend_leaders import read_compute, read_chart

DB_PATH = os.environ.get('EXPLORER_PUBLIC_KR_SEASON_DB')
COLUMNS = {
    'stock_prices': {'stock_code', 'trade_date', 'high', 'low', 'close', 'volume', 'market_cap', 'fetched_at'},
    'companies': {'stock_code', 'corp_name'},
    'public_kr_company_sectors': {'stock_code', 'sector'},
}


def authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT: return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and database == 'main' and column in COLUMNS.get(table, set()):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and column == 'max': return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def connection(path=None):
    if not (path or DB_PATH): raise sqlite3.OperationalError('Public KR market snapshot unavailable')
    conn = sqlite3.connect(Path(path or DB_PATH).resolve().as_uri()+'?mode=ro', uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON'); conn.execute('BEGIN')
    conn.set_authorizer(authorize)
    return conn


def stored_trends(*, path=None):
    if not (path or DB_PATH): raise sqlite3.OperationalError('Public KR market snapshot unavailable')
    snapshot = Path(path or DB_PATH).resolve()
    stat = snapshot.stat()
    return _snapshot_trends(str(snapshot), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=1)
def _snapshot_trends(path, device, inode, size, modified):
    # Prepared files are immutable while served and replaced atomically on update.
    # A replacement gets its own cache; no private pipeline cache is shared.
    with closing(connection(path)) as conn:
        sectors = dict(conn.execute('SELECT stock_code, sector FROM public_kr_company_sectors'))
        return read_compute(conn, sectors=sectors)


def stored_chart(code, *, path=None):
    with closing(connection(path)) as conn:
        return read_chart(conn, code)
