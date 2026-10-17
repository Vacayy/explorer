"""가파른 추세 종목 API — 홈 위젯용 (pipeline/trend_leaders, LLM 0·네트워크 0)."""
from fastapi import APIRouter

from models.trend import TrendLeadersResponse

router = APIRouter(prefix="/api/spine/trend-leaders", tags=["spine"])


@router.get("", response_model=TrendLeadersResponse)
def trend_leaders():
    from pipeline.trend_leaders import compute
    return compute()
