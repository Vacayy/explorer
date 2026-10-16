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
    stored_only: bool = False,
):
    if stored_only:
        from datetime import datetime
        from services.dart_service import _corp_code_for_stock, _build_financial_response
        corp = _corp_code_for_stock(stock_code)
        year = datetime.now().year
        result = _build_financial_response(corp or "", sj_div, period, year-years, year, fs_div)
        if not result["rows"] and fs_div == "CFS":
            result = _build_financial_response(corp or "", sj_div, period, year-years, year, "OFS")
        return result
    return fetch_financial_statements(stock_code, sj_div, period, years, fs_div)
