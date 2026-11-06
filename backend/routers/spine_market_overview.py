"""홈 › 한국 시장 · 미국 시장 ① 지수 차트 + 요약 지표 (ia-redesign §4.2·4.3, D-325).

GET /api/spine/market/{kr|us}/overview — 지수(1일 장중 경로·1개월·3개월·1년)와 요약 지표 4칸. 저장분만 읽는다(외부 호출 0, LLM 0).
장중 경로는 launchd `indexintraday`(scripts/index_intraday.py)가 10분마다 쌓는다.
"""
from typing import Literal

from fastapi import APIRouter

from database import get_connection
from models.market_overview import MarketOverview
from pipeline.market_overview import overview

router = APIRouter(prefix="/api/spine/market", tags=["spine"])


@router.get("/{market}/overview", response_model=MarketOverview)
def market_overview(market: Literal["kr", "us"]):
    conn = get_connection()
    try:
        return overview(conn, market)
    finally:
        conn.close()
