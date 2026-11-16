"""Local-only saved admin reads from the older rehearsal snapshot.

This is not live scheduler status. The DB is mounted read-only and no worker
or write endpoint is started. Observe's in-process usage queue is empty here.
"""
from datetime import datetime, timedelta

from fastapi import FastAPI
import uvicorn

from database import get_connection
from pipeline import observe
from routers import spine_admin

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
observe.flush = lambda: None


@app.get('/api/spine/admin/jobs')
def jobs():
    return spine_admin.jobs()


@app.get('/api/spine/admin/runs')
def runs(limit: int = 50):
    return spine_admin.runs(limit=max(1, min(limit, 500)))


@app.get('/api/spine/admin/observe')
def observation(days: int = 7):
    return observe.summary(max(1, min(days, 90)))


@app.get('/api/stock-prices/{stock_code}')
def saved_stock_prices(stock_code: str, from_date: str | None = None, to_date: str | None = None):
    # Original price route refreshes the network cache when stale; this local
    # adapter exposes only rows already in the historical snapshot.
    from services.krx_service import _fmt
    to_date = to_date or datetime.now().strftime('%Y%m%d')
    from_date = from_date or (datetime.now() - timedelta(days=365 * 5)).strftime('%Y%m%d')
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT trade_date, open, high, low, close, volume, market_cap FROM stock_prices '
            'WHERE stock_code=? AND trade_date>=? AND trade_date<=? ORDER BY trade_date',
            (stock_code, _fmt(from_date), _fmt(to_date)),
        ).fetchall()
        return {'items': [dict(row) for row in rows]}
    finally:
        conn.close()


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)
