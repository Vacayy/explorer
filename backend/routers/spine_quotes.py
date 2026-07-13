"""실시간 시세 프록시 — 네이버 polling API (지연 0, 권장 폴링 7초).

stock_prices 테이블은 일 1회 종가 수집이라 장중에는 낡는다 — 현재가 표시는
이 엔드포인트가 담당 (10초 인메모리 캐시로 상류 배려).
"""
from fastapi import APIRouter, Query
from pydantic import BaseModel

from pipeline.quotes import fetch_quotes

router = APIRouter(prefix="/api/spine/quotes", tags=["spine"])


class Quote(BaseModel):
    stock_code: str
    price: float | None
    change: float | None
    change_pct: float | None
    volume: float | None
    market_status: str | None   # OPEN | CLOSE 등
    traded_at: str | None


@router.get("", response_model=list[Quote])
def get_quotes(codes: str = Query(..., description="쉼표 구분 종목코드")):
    return [Quote(**q) for q in fetch_quotes(codes.split(","))]
