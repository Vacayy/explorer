"""Small, read-only in-memory projections for reusing existing read functions."""
from contextlib import contextmanager
import sqlite3
import uuid


@contextmanager
def price_history_projection(rows):
    """Expose only the already selected PG price rows to the existing SQL."""
    uri = f'file:chat-prices-{uuid.uuid4().hex}?mode=memory&cache=shared'
    root = sqlite3.connect(uri, uri=True)
    try:
        root.execute('CREATE TABLE stock_prices(stock_code TEXT,trade_date TEXT,open INTEGER,high INTEGER,'
                     'low INTEGER,close INTEGER,volume INTEGER,fetched_at TEXT)')
        root.executemany('INSERT INTO stock_prices VALUES(?,?,?,?,?,?,?,?)', rows)
        root.commit()

        def connect():
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA query_only=ON')
            return conn

        yield connect
    finally:
        root.close()
