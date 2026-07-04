from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import get_connection
from services.telegram_service import scrape_channel, get_channel_display_name

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

CACHE_TTL_MINUTES = 60


class AddChannelRequest(BaseModel):
    url: str


class ToggleChannelRequest(BaseModel):
    is_active: bool


def _extract_channel_name(url: str) -> str:
    url = url.strip().rstrip("/")
    if "t.me/" in url:
        parts = url.split("t.me/")
        name = parts[-1].lstrip("s/").strip("/")
        return name.split("/")[0]
    return url


def _is_cache_fresh(last_fetched: str | None) -> bool:
    if not last_fetched:
        return False
    try:
        dt = datetime.fromisoformat(last_fetched)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - dt < timedelta(minutes=CACHE_TTL_MINUTES)
    except Exception:
        return False


# ── Channels CRUD ────────────────────────────────────────────────

@router.get("/channels")
def list_channels():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, channel_name, display_name, is_active, last_fetched_at, added_at FROM telegram_channels ORDER BY added_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/channels", status_code=201)
def add_channel(body: AddChannelRequest):
    channel_name = _extract_channel_name(body.url)
    if not channel_name:
        raise HTTPException(400, "유효한 채널 URL을 입력해주세요")

    # Check if already exists (reactivate if inactive)
    conn = get_connection()
    existing = conn.execute(
        "SELECT id, is_active FROM telegram_channels WHERE channel_name = ?", (channel_name,)
    ).fetchone()
    if existing:
        if not existing["is_active"]:
            conn.execute("UPDATE telegram_channels SET is_active = 1 WHERE id = ?", (existing["id"],))
            conn.commit()
        row = conn.execute(
            "SELECT id, channel_name, display_name, is_active, last_fetched_at, added_at FROM telegram_channels WHERE id = ?",
            (existing["id"],),
        ).fetchone()
        conn.close()
        return dict(row)
    conn.close()

    display_name = get_channel_display_name(channel_name)
    if display_name is None:
        raise HTTPException(422, "채널을 찾을 수 없습니다. 공개 채널인지 확인해주세요")

    conn = get_connection()
    conn.execute(
        "INSERT INTO telegram_channels (channel_name, display_name, is_active) VALUES (?, ?, 1)",
        (channel_name, display_name),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, channel_name, display_name, is_active, last_fetched_at, added_at FROM telegram_channels WHERE channel_name = ?",
        (channel_name,),
    ).fetchone()
    conn.close()
    return dict(row)


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


# ── Feed ─────────────────────────────────────────────────────────

def _fetch_and_cache(channel_name: str) -> None:
    messages = scrape_channel(channel_name)
    if not messages:
        return
    conn = get_connection()
    for m in messages:
        conn.execute(
            """INSERT OR REPLACE INTO telegram_messages
               (channel_name, message_id, content, date, link, fetched_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (channel_name, m["message_id"], m["content"], m["date"], m["link"]),
        )
    conn.execute(
        "UPDATE telegram_channels SET last_fetched_at = datetime('now') WHERE channel_name = ?",
        (channel_name,),
    )
    conn.commit()
    conn.close()


def _messages_for_channel(channel_name: str) -> list[dict]:
    conn = get_connection()
    ch = conn.execute(
        "SELECT last_fetched_at FROM telegram_channels WHERE channel_name = ?", (channel_name,)
    ).fetchone()
    conn.close()

    if ch and _is_cache_fresh(ch["last_fetched_at"]):
        # Use cached
        conn = get_connection()
        rows = conn.execute(
            "SELECT channel_name, message_id, content, date, link FROM telegram_messages WHERE channel_name = ? ORDER BY date DESC",
            (channel_name,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    _fetch_and_cache(channel_name)

    conn = get_connection()
    rows = conn.execute(
        "SELECT channel_name, message_id, content, date, link FROM telegram_messages WHERE channel_name = ? ORDER BY date DESC",
        (channel_name,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/feed")
def get_feed():
    conn = get_connection()
    channels = conn.execute(
        "SELECT channel_name FROM telegram_channels WHERE is_active = 1"
    ).fetchall()
    conn.close()

    all_messages: list[dict] = []
    for ch in channels:
        msgs = _messages_for_channel(ch["channel_name"])
        all_messages.extend(msgs)

    all_messages.sort(key=lambda m: m.get("date") or "", reverse=True)
    return {"items": all_messages, "total": len(all_messages)}


@router.get("/feed/{channel_name}")
def get_channel_feed(channel_name: str):
    conn = get_connection()
    row = conn.execute("SELECT id FROM telegram_channels WHERE channel_name = ?", (channel_name,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "채널을 찾을 수 없습니다")
    msgs = _messages_for_channel(channel_name)
    return {"items": msgs, "total": len(msgs)}
