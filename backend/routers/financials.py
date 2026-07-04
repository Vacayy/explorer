from fastapi import APIRouter, Query
from services.dart_service import fetch_financial_statements

router = APIRouter(prefix="/api/financials", tags=["financials"])


@router.get("/{stock_code}")
def get_financials(
    stock_code: str,
    sj_div: str = Query("IS", pattern="^(IS|BS|CF|CIS)$"),
    period: str = Query("annual", pattern="^(annual|quarterly|trailing)$"),
    years: int = Query(5, ge=1, le=20),
    fs_div: str = Query("CFS", pattern="^(CFS|OFS)$"),
):
    return fetch_financial_statements(stock_code, sj_div, period, years, fs_div)
