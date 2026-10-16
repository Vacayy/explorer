from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import get_connection

router = APIRouter(prefix="/api/telegram", tags=["telegram"])
# 텔레그램 채널 목록·켜기/끄기만 — 등록·수집은 spine_sources·ingest가 맡는다. 구 피드(telegram_messages)는 D-241로 제거

class ToggleChannelRequest(BaseModel):
    is_active: bool


# ── Channels CRUD ────────────────────────────────────────────────

@router.get("/channels")
def list_channels():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, channel_name, display_name, is_active, last_fetched_at, added_at FROM telegram_channels ORDER BY added_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.put("/channels/{channel_id}/toggle")
def toggle_channel(channel_id: int, body: ToggleChannelRequest):
    conn = get_connection()
    existing = conn.execute("SELECT id FROM telegram_channels WHERE id = ?", (channel_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "채널을 찾을 수 없습니다")
    conn.execute("UPDATE telegram_channels SET is_active = ? WHERE id = ?", (1 if body.is_active else 0, channel_id))
    conn.commit()
    row = conn.execute(
        "SELECT id, channel_name, display_name, is_active, last_fetched_at, added_at FROM telegram_channels WHERE id = ?",
        (channel_id,),
    ).fetchone()
    conn.close()
    return dict(row)
