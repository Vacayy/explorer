"""실시간 시세 프록시 — 네이버 polling API (지연 0, 권장 폴링 7초).

stock_prices 테이블은 일 1회 종가 수집이라 장중에는 낡는다 — 현재가 표시는
이 엔드포인트가 담당 (10초 인메모리 캐시로 상류 배려).
"""
import time

import requests
from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/spine/quotes", tags=["spine"])

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_API = "https://polling.finance.naver.com/api/realtime/domestic/stock/{codes}"
_TTL = 10  # 초
_cache: dict[str, tuple[float, list]] = {}


class Quote(BaseModel):
    stock_code: str
    price: float | None
    change: float | None
    change_pct: float | None
    volume: float | None
    market_status: str | None   # OPEN | CLOSE 등
    traded_at: str | None


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


@router.get("", response_model=list[Quote])
def get_quotes(codes: str = Query(..., description="쉼표 구분 종목코드")):
    key = ",".join(sorted(set(c.strip() for c in codes.split(",") if c.strip())))[:400]
    if not key:
        return []
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    try:
        r = requests.get(_API.format(codes=key), headers=_UA, timeout=10)
        r.raise_for_status()
        datas = r.json().get("datas") or []
    except Exception:
        return hit[1] if hit else []
    out = [Quote(
        stock_code=d.get("itemCode", ""),
        price=_num(d.get("closePrice")),
        change=_num(d.get("compareToPreviousClosePrice")),
        change_pct=_num(d.get("fluctuationsRatio")),
        volume=_num(d.get("accumulatedTradingVolume")),
        market_status=d.get("marketStatus"),
        traded_at=d.get("localTradedAt"),
    ) for d in datas]
    _cache[key] = (now, out)
    return out
