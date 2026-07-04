"""Company comparison endpoint — returns KPI data for multiple stocks side by side."""
from fastapi import APIRouter, Query
from database import get_connection
from routers.kpi import get_kpi

router = APIRouter(prefix="/api/compare", tags=["compare"])


def _get_corp_name(stock_code: str) -> str | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT corp_name FROM companies WHERE stock_code = ?", (stock_code,)
    ).fetchone()
    conn.close()
    return row["corp_name"] if row else None


@router.get("")
def compare_stocks(stocks: str = Query(..., description="Comma-separated stock codes")):
    """Return KPI data for multiple stocks. e.g. ?stocks=403870,272110,036930"""
    stock_codes = [s.strip() for s in stocks.split(",") if s.strip()]
    items = []
    for code in stock_codes:
        try:
            kpi = get_kpi(code)
            kpi["corp_name"] = _get_corp_name(code)
            items.append(kpi)
        except Exception:
            # Skip stocks that are not found rather than failing the whole request
            pass
    return {"items": items}
