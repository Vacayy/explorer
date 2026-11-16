"""가파른 추세 종목 API — 홈 위젯용 (pipeline/trend_leaders, LLM 0·네트워크 0)."""
from fastapi import APIRouter, Path, Request

from models.trend import TrendChart, TrendLeadersResponse

router = APIRouter(prefix="/api/spine/trend-leaders", tags=["spine"])


@router.get("", response_model=TrendLeadersResponse)
def trend_leaders(request: Request):
    if getattr(request.state, "public_access", False):
        from security.public_trend import stored_trends
        from routers.public_documents import perform
        return perform(stored_trends)
    from pipeline.trend_leaders import compute
    return compute()


@router.get("/{code}/chart", response_model=TrendChart)
def trend_chart(request: Request, code: str = Path(pattern=r"^[0-9A-Z]{6}$")):
    """근거 창 차트 ≈ 2년(500거래일) — 목록 응답을 가볍게 두려고 따로 받는다"""
    if getattr(request.state, "public_access", False):
        from security.public_trend import stored_chart
        from routers.public_documents import perform
        return perform(lambda: stored_chart(code))
    from pipeline.trend_leaders import chart
    return chart(code)
