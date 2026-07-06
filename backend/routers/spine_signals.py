"""신호 API — signals 테이블 읽기."""
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Query
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
