from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import get_connection

router = APIRouter(prefix="/api/blog", tags=["blog"])
# 블로그 소스 목록·켜기/끄기만 — 등록·수집은 spine_sources·ingest가 맡는다. 구 피드(blog_posts)는 D-241로 제거

class ToggleSourceRequest(BaseModel):
    is_active: bool


# ── Sources CRUD ─────────────────────────────────────────────────

@router.get("/sources")
def list_sources():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, url, platform, blog_name, author, is_active, last_fetched_at, added_at FROM blog_sources ORDER BY added_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.put("/sources/{source_id}/toggle")
def toggle_source(source_id: int, body: ToggleSourceRequest):
    conn = get_connection()
    existing = conn.execute("SELECT id FROM blog_sources WHERE id = ?", (source_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "블로그 소스를 찾을 수 없습니다")
    conn.execute(
        "UPDATE blog_sources SET is_active = ? WHERE id = ?",
        (1 if body.is_active else 0, source_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, url, platform, blog_name, is_active, last_fetched_at, added_at FROM blog_sources WHERE id = ?",
        (source_id,),
    ).fetchone()
    conn.close()
    return dict(row)
