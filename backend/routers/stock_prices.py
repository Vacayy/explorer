from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from services.krx_service import fetch_stock_prices, fetch_fundamentals, compute_pbr_bands
from database import get_connection

router = APIRouter(prefix="/api", tags=["stock_prices"])


@router.get("/stock-prices/{stock_code}")
def get_stock_prices(
    stock_code: str,
    from_date: str = Query(None),
    to_date: str = Query(None),
):
    if not to_date:
        to_date = datetime.now().strftime("%Y%m%d")
    if not from_date:
        from_date = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y%m%d")
    items = fetch_stock_prices(stock_code, from_date, to_date)
    return {"items": items}


@router.get("/valuation/{stock_code}")
def get_valuation(
    stock_code: str,
    from_date: str = Query(None),
    to_date: str = Query(None),
):
    if not to_date:
        to_date = datetime.now().strftime("%Y%m%d")
    if not from_date:
        from_date = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y%m%d")

    items = fetch_fundamentals(stock_code, from_date, to_date)
    pbr_bands = compute_pbr_bands(stock_code, from_date, to_date)
    return {"items": items, "pbr_bands": pbr_bands}


@router.get("/stock-prices/{stock_code}/snapshot")
def get_price_snapshot(stock_code: str, days: int = Query(10, ge=2, le=120)):
    """stock_prices 테이블만 읽는 최근 N거래일 시세 — 외부 호출 0, LLM 0.

    대화 답변의 시세 차트 카드용(docs/specs/chat-page.md §4): 답변이 인용한 get_price_history와
    같은 테이블·같은 16:10 스냅샷을 그려 본문 숫자와 차트가 어긋나지 않게 한다.
    (/stock-prices/{code}는 캐시 미스 시 pykrx를 부르므로 대화 안에서는 쓰지 않는다)
    """
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT trade_date, open, high, low, close, volume FROM stock_prices
            WHERE stock_code=? ORDER BY trade_date DESC LIMIT ?""", (stock_code, days + 1)).fetchall()[::-1]
        name = conn.execute("SELECT corp_name FROM companies WHERE stock_code=?", (stock_code,)).fetchone()
    finally:
        conn.close()
    return {"stock_code": stock_code, "name": name["corp_name"] if name else stock_code,
            "items": [dict(r) for r in rows]}
