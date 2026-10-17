"""대만 월매출 API — 홈 위젯용 (pipeline/tw_revenue, LLM·네트워크 0)."""
from fastapi import APIRouter, Query

from models.tw import TwLinksResponse, TwRevenueResponse

router = APIRouter(prefix="/api/spine/tw", tags=["spine"])


@router.get("/revenue", response_model=TwRevenueResponse)
def tw_revenue(months: int = Query(36, ge=3, le=120)):
    from pipeline.tw_revenue import read
    return read(months)


@router.get("/links", response_model=TwLinksResponse)
def tw_links(kr: str | None = None):
    """대만 → 한국 연결 — 연결별 대만 신호(3개월 YoY·가속/둔화)와 숫자 근거(시차별 상관)"""
    from pipeline.tw_links import read_links
    return read_links(kr)
