"""Read boundary for the existing market overview projection, not arbitrary SQL."""
from pathlib import Path
import sqlite3

from config import DB_PATH


MARKET_COLUMNS = {
    'market_indicators': {'snapshot_date', 'indicator', 'value', 'fetched_at'},
    'index_intraday': {'key', 'trade_date', 'hhmm', 'value'},
    'retail_flows': {'date', 'credit_total', 'indiv_buy', 'indiv_sell'},
    'stock_prices': {'stock_code', 'trade_date', 'close'},
}
MARKET_FUNCTIONS = {'max', 'count', 'date', 'coalesce', 'sum'}


def _authorize(action, first, second, database, source):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        # SQLite's optimized COUNT(*) reports an empty column and may omit the
        # database name. ATTACH/temp creation are denied by this connection.
        main_read = database == 'main' or (database is None and second == '')
        if main_read and first in MARKET_COLUMNS and (second == '' or second in MARKET_COLUMNS[first]):
            return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and second in MARKET_FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def market_connection(path: Path | None = None) -> sqlite3.Connection:
    # mode=ro preserves live WAL visibility; immutable=1 would be incorrect here.
    # No mkdir/schema setup/journal-mode changes or extension loading.
    conn = sqlite3.connect(Path(path or DB_PATH).resolve().as_uri() + '?mode=ro', uri=True, timeout=3)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.set_authorizer(_authorize)
        return conn
    except Exception:
        conn.close()
        raise
