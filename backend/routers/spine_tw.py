"""대만 월매출 API — 홈 위젯용 (pipeline/tw_revenue, LLM·네트워크 0)."""
from fastapi import APIRouter, Query

from models.tw import TwRevenueResponse

router = APIRouter(prefix="/api/spine/tw", tags=["spine"])


@router.get("/revenue", response_model=TwRevenueResponse)
def tw_revenue(months: int = Query(36, ge=3, le=120)):
    from pipeline.tw_revenue import read
    return read(months)
