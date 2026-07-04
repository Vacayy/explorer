from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from services.krx_service import fetch_stock_prices, fetch_fundamentals, compute_pbr_bands

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
