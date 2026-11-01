"""가파른 추세 종목 API — 홈 위젯용 (pipeline/trend_leaders, LLM 0·네트워크 0)."""
from fastapi import APIRouter, Path

from models.trend import TrendChart, TrendLeadersResponse

router = APIRouter(prefix="/api/spine/trend-leaders", tags=["spine"])


@router.get("", response_model=TrendLeadersResponse)
def trend_leaders():
    from pipeline.trend_leaders import compute
    return compute()


@router.get("/{code}/chart", response_model=TrendChart)
def trend_chart(code: str = Path(pattern=r"^[0-9A-Z]{6}$")):
    """근거 창 차트 ≈ 2년(500거래일) — 목록 응답을 가볍게 두려고 따로 받는다"""
    from pipeline.trend_leaders import chart
    return chart(code)
