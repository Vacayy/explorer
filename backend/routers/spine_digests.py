"""종목 언급 다이제스트 API — 1D/7D 요약 + 새로운 시각."""
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/digests", tags=["spine"])


class DigestItem(BaseModel):
    period: str          # 1d | 7d
    period_start: str    # KST 날짜 (7d는 기준일)
    digest: str | None
    insights: str | None # 이전 요약 대비 새로운 시각 (epistemic: 가설)
    doc_count: int | None
    model: str | None


class DigestsResponse(BaseModel):
    items: list[DigestItem]
    as_of: str


class DigestComputeResult(BaseModel):
    status: str                  # ok | empty | unavailable
    item: DigestItem | None = None


@router.get("", response_model=DigestsResponse)
def list_digests(
    stock: str = Query(..., description="종목코드"),
    period: str = Query("1d", pattern="^(1d|7d)$"),
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


@router.post("/compute", response_model=DigestComputeResult)
def compute_digest(
    stock: str = Query(..., description="종목코드"),
    period: str = Query("1d", pattern="^(1d|7d)$"),
):
    """온디맨드 다이제스트 새로고침 — 해당 종목·기간을 지금 한 번 생성(force).
    period_start=당일(KST)이라 오늘 이미 생성분이 있으면 덮어쓴다(하루 다중 생성 방지)."""
    from pipeline.digests import compute_daily, compute_rolling7, KST
    stats = (compute_daily(stock_code=stock, force=True) if period == "1d"
             else compute_rolling7(stock_code=stock, force=True))
    if stats.get("skipped"):
        return DigestComputeResult(status="unavailable")

    today = datetime.now(KST).date().isoformat()
    conn = get_connection()
    row = conn.execute("""
        SELECT d.period, d.period_start, d.digest, d.insights, d.doc_count, d.model
        FROM entity_digests d JOIN entities e ON d.entity_id = e.id
        WHERE e.type='company' AND e.aliases=? AND d.period=? AND d.period_start=?
    """, (stock, period, today)).fetchone()
    conn.close()
    if not row:
        return DigestComputeResult(status="empty")
    return DigestComputeResult(status="ok", item=DigestItem(**dict(row)))
