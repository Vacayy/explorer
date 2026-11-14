from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query
from models.income_flow import IncomeFlowQuarters, IncomeFlowResponse
from pipeline.income_flow import kr_income_flow, kr_income_flow_quarters
from services.dart_service import _corp_code_for_stock, fetch_financial_statements


class CollectStats(BaseModel):
    """한 종목 재무 수집 결과 — kr_company_data.collect_financials 통계의 요약."""
    stock_code: str
    periods_added: int
    rows: int
    no_data: int
    failed: int
    companies_checked: int
    targets: int
    calls: int

router = APIRouter(prefix="/api/financials", tags=["financials"])


@router.get("/{stock_code}/income-flow/quarters", response_model=IncomeFlowQuarters)
def get_income_flow_quarters(stock_code: str):
    """분기 손익 흐름 — 선택 가능한 분기 목록(최신 → 과거 8개). 비면 빈 리스트."""
    return kr_income_flow_quarters(stock_code)


@router.get("/{stock_code}/income-flow", response_model=IncomeFlowResponse)
def get_income_flow(
    stock_code: str,
    q: str | None = Query(None, pattern=r"^\d{2}\.(03|06|09|12)$"),
    mode: str = Query("q", pattern="^(q|ttm)$"),
):
    """분기 손익 흐름(Sankey) — ia-redesign §4.13. q 생략 시 최신 분기. mode=ttm은 최근 4분기 합."""
    result = kr_income_flow(stock_code, q, mode)
    if result is None:
        raise HTTPException(404, detail="분기 손익 자료가 없습니다")
    return result


@router.post("/{stock_code}/collect", response_model=CollectStats)
def collect_financials_for_stock(stock_code: str):
    """한 종목만 DART에서 분기 재무를 받아 저장(사용자 재공시 트리거).

    보유·관심·시총 상위 N개만 정기 수집하는 krcompany 체인(`kr_company_data.targets`)의 사각지대에
    들어오는 소형주 — 처음 눌렀을 때 재무가 들어와야 '분기 손익 흐름' Sankey가 그려진다.
    예산 32콜(한 종목 최근 5년 × 4보고×2 fs_div 상한) 안에서만 돈다.
    """
    from config import DART_API_KEY
    from datetime import datetime, timedelta, timezone
    from database import get_connection
    from pipeline import kr_company_data as kr

    corp = _corp_code_for_stock(stock_code)
    if not corp:
        raise HTTPException(404, detail="종목을 찾을 수 없습니다 (companies 미등록)")
    today = datetime.now(timezone(timedelta(hours=9))).date()
    client = kr.DartClient(DART_API_KEY, budget=40)
    conn = get_connection()
    try:
        stats = kr.collect_financials(conn, client, [{"corp_code": corp, "stock_code": stock_code, "tier": "on_demand"}], today)
    finally:
        conn.close()
    return CollectStats(stock_code=stock_code, periods_added=stats.get("periods_added", 0),
                        rows=stats.get("rows", 0), no_data=stats.get("no_data", 0),
                        failed=stats.get("failed", 0), companies_checked=stats.get("companies_checked", 0),
                        targets=stats.get("targets", 0), calls=stats.get("calls", 0))


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
