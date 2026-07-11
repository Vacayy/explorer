"""신호 API — signals 테이블 읽기."""
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel
from database import get_connection
from models.spine import SignalItem, SignalsResponse

router = APIRouter(prefix="/api/spine/signals", tags=["spine"])


def _row_to_item(r) -> SignalItem:
    return SignalItem(
        id=r["id"], signal_type=r["signal_type"], entity_id=r["entity_id"],
        entity_name=r["entity_name"], stock_code=r["stock_code"], date=r["date"],
        payload=json.loads(r["payload_json"] or "{}"),
        interpretation=r["interpretation"],
        interpretation_model=r["interpretation_model"],
    )


@router.get("", response_model=SignalsResponse)
def get_signals(
    type: str | None = Query(None, description="mention_surge 등"),
    days: int = Query(7, ge=1, le=90),
):
    conn = get_connection()
    where, params = ["s.date >= ?"], [(date.today() - timedelta(days=days)).isoformat()]
    if type:
        where.append("s.signal_type = ?")
        params.append(type)

    rows = conn.execute(f"""
        SELECT s.id, s.signal_type, s.entity_id, s.date, s.payload_json,
               s.interpretation, s.interpretation_model,
               e.name AS entity_name, e.aliases AS stock_code
        FROM signals s JOIN entities e ON s.entity_id = e.id
        WHERE {" AND ".join(where)}
        ORDER BY s.date DESC, s.id DESC
    """, params).fetchall()
    conn.close()

    return SignalsResponse(
        items=[_row_to_item(r) for r in rows],
        as_of=datetime.now(timezone.utc).isoformat(),
    )


class MomentumRow(BaseModel):
    rank: int
    entity_id: int
    name: str
    stock_code: str | None
    count_7d: int
    prior_7d: int
    score: float          # count_7d / max(prior,1) — 부상 배율


class MomentumResponse(BaseModel):
    items: list[MomentumRow]
    as_of: str


@router.get("/momentum", response_model=MomentumResponse)
def mention_momentum(limit: int = Query(12, ge=3, le=30)):
    """언급 모멘텀 랭킹 — 이번 주 부상 중인 종목 (카운트→발굴 확장)."""
    from pipeline.dates import parse_dt  # noqa: F401 (published_at ISO 정규화 전제)
    conn = get_connection()
    rows = conn.execute("""
        SELECT e.id entity_id, e.name, e.aliases stock_code,
               sum(rd.published_at >= datetime('now', '-7 days')) c7,
               sum(rd.published_at < datetime('now', '-7 days')
                   AND rd.published_at >= datetime('now', '-14 days')) p7
        FROM entity_links el
        JOIN entities e ON el.entity_id = e.id
        JOIN raw_documents rd ON el.doc_id = rd.id
        WHERE el.link_type = 'stock' AND e.type = 'company'
        GROUP BY e.id
        HAVING c7 >= 2
    """).fetchall()
    conn.close()

    scored = sorted(
        ({"entity_id": r["entity_id"], "name": r["name"], "stock_code": r["stock_code"],
          "count_7d": r["c7"] or 0, "prior_7d": r["p7"] or 0,
          "score": round((r["c7"] or 0) / max(r["p7"] or 0, 1), 1)}
         for r in rows),
        key=lambda x: (-x["score"], -x["count_7d"]),
    )[:limit]
    return MomentumResponse(
        items=[MomentumRow(rank=i + 1, **s) for i, s in enumerate(scored)],
        as_of=datetime.now(timezone.utc).isoformat(),
    )
