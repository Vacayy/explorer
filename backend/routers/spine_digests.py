"""종목 언급 다이제스트 API — 1D/7D 요약 + 새로운 시각."""
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/digests", tags=["spine"])


class DigestItem(BaseModel):
    period: str          # 1d | 1w | 1m (캘린더 기준, D-085)
    period_start: str    # KST 날짜 — 1d=당일, 1w=그 주 월요일, 1m=그 달 1일
    digest: str | None
    insights: str | None # 이전 요약 대비 새로운 시각 (epistemic: 가설)
    doc_count: int | None
    model: str | None


class DigestsResponse(BaseModel):
    items: list[DigestItem]
    as_of: str


class CatchupResult(BaseModel):
    status: str                  # ok | unavailable
    monthly: int = 0
    weekly: int = 0
    daily: int = 0
    unchanged: int = 0


@router.get("", response_model=DigestsResponse)
def list_digests(
    stock: str = Query(..., description="종목코드"),
    period: str = Query("1d", pattern="^(1d|1w|1m)$"),
    limit: int = Query(10, ge=1, le=60),
):
    conn = get_connection()
    rows = conn.execute("""
        SELECT d.period, d.period_start, d.digest, d.insights, d.doc_count, d.model
        FROM entity_digests d
        JOIN entities e ON d.entity_id = e.id
        WHERE e.type='company' AND e.aliases = ? AND d.period = ?
        ORDER BY d.period_start DESC LIMIT ?
    """, (stock, period, limit)).fetchall()
    conn.close()
    return DigestsResponse(
        items=[DigestItem(**dict(r)) for r in rows],
        as_of=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/catchup", response_model=CatchupResult)
def catchup(stock: str = Query(..., description="종목코드")):
    """진입 시 소급 생성(D-085) — 과거 완결 월 1M · 이번 달 주 1W · 오늘 1D를 멱등 채움.
    프론트가 종목 진입 시 자동 호출(백그라운드). 이미 있으면 unchanged로 스킵(재진입 무비용)."""
    from pipeline.digests import catch_up
    r = catch_up(stock)
    if r.get("skipped"):
        return CatchupResult(status="unavailable")
    return CatchupResult(status="ok", monthly=r.get("monthly", 0), weekly=r.get("weekly", 0),
                         daily=r.get("daily", 0), unchanged=r.get("unchanged", 0))
