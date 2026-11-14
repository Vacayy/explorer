"""Readonly public ETF map input, excluding all personal follow/document data."""
from pathlib import Path
import sqlite3

from config import DB_PATH


def _authorize(action, first, second, database, source):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if (action == sqlite3.SQLITE_READ and database == 'main'
            and first == 'sector_benchmark_prices'
            and second in {'ticker', 'trade_date', 'close'}):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def industry_connection(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path or DB_PATH).resolve().as_uri() + '?mode=ro', uri=True, timeout=3)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.set_authorizer(_authorize)
        return conn
    except Exception:
        conn.close()
        raise
