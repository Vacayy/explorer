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
