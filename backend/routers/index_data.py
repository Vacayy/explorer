from fastapi import APIRouter, Query
from datetime import datetime, timedelta
# yfinance lazy-imported inside endpoint to avoid slow startup
from database import get_connection

router = APIRouter(prefix="/api/index", tags=["index"])


@router.get("/performance/{stock_code}")
def get_relative_performance(stock_code: str, days: int = Query(365)):
    """Return normalized performance of stock vs KOSPI/KOSDAQ index."""
    to_date = datetime.now().strftime("%Y%m%d")
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    conn = get_connection()
    stock_rows = conn.execute(
        "SELECT trade_date, close FROM stock_prices WHERE stock_code = ? AND trade_date >= ? ORDER BY trade_date",
        (stock_code, f"{from_date[:4]}-{from_date[4:6]}-{from_date[6:8]}")
    ).fetchall()

    company = conn.execute(
        "SELECT market FROM companies WHERE stock_code = ?", (stock_code,)
    ).fetchone()
    conn.close()

    market = "KOSDAQ" if company and company["market"] and "KOSDAQ" in company["market"].upper() else "KOSPI"
    index_ticker = "^KQ11" if market == "KOSDAQ" else "^KS11"

    try:
        import yfinance as yf
        idx = yf.Ticker(index_ticker)
        fd = f"{from_date[:4]}-{from_date[4:6]}-{from_date[6:8]}"
        td = f"{to_date[:4]}-{to_date[4:6]}-{to_date[6:8]}"
        hist = idx.history(start=fd, end=td)
        index_map = {}
        for date_idx in hist.index:
            d = date_idx.strftime("%Y-%m-%d")
            index_map[d] = float(hist.loc[date_idx]["Close"])
    except Exception:
        index_map = {}

    if not stock_rows:
        return {"stock_code": stock_code, "market": market, "data": []}

    stock_base = stock_rows[0]["close"] if stock_rows[0]["close"] else 1

    index_base = None
    for r in stock_rows:
        if r["trade_date"] in index_map:
            index_base = index_map[r["trade_date"]]
            break
    if index_base is None:
        index_base = 1

    result = []
    for r in stock_rows:
        d = r["trade_date"]
        stock_norm = round((r["close"] / stock_base) * 100, 2) if r["close"] else None
        idx_close = index_map.get(d)
        index_norm = round((idx_close / index_base) * 100, 2) if idx_close else None
        result.append({"date": d, "stock": stock_norm, "index": index_norm})

    return {"stock_code": stock_code, "market": market, "data": result}
