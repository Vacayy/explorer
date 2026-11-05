"""Market Today API (docs/specs/market-today.md) — 장중 회차 화두 요약 읽기. 생성은 정기 작업(scripts/market_today.py)."""
from fastapi import APIRouter, Query

from models.market_today import MarketToday

router = APIRouter(tags=["spine"])


@router.get("/api/spine/market-today", response_model=MarketToday)
def market_today(date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                 slot: str | None = Query(None, pattern=r"^(0930|1130|1500|1600|1000|1300|1540)$")):
    """그날(없으면 최근) 회차 목록과 선택(없으면 최신) 회차의 화두·출처. LLM 0."""
    from pipeline.market_today import read
    return read(date, slot)
