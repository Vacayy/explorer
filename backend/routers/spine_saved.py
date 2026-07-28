"""저장됨(북마크) CRUD — 특정 산출물 다시 찾기 (D-078, docs/specs/saved-items.md).

기업·문서·내러티브·리포트 페이지를 저장. 내러티브·리포트는 버전 행 PK를 ref로 저장(보던 그 버전 고정).
팔로우(엔티티 흐름 구독)와 성격이 다른 아티팩트 북마크.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/saved", tags=["spine"])


class SavedItem(BaseModel):
    id: int
    kind: str            # company | doc | narrative | report
    ref: str
    url: str
    title: str | None = None
    subtitle: str | None = None
    note: str | None = None
    created_at: str | None = None


class SaveRequest(BaseModel):
    kind: str
    ref: str
    url: str
    title: str | None = None
    subtitle: str | None = None
    note: str | None = None


class NoteRequest(BaseModel):
    note: str | None = None


@router.get("", response_model=list[SavedItem])
def list_saved(kind: str | None = None):
    conn = get_connection()
    if kind:
        rows = conn.execute(
            "SELECT * FROM saved_items WHERE kind=? ORDER BY created_at DESC, id DESC", (kind,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM saved_items ORDER BY created_at DESC, id DESC").fetchall()
    conn.close()
    return [SavedItem(**dict(r)) for r in rows]


@router.post("", response_model=SavedItem, status_code=201)
def add_saved(body: SaveRequest):
    if body.kind not in ("company", "doc", "narrative", "report"):
        raise HTTPException(400, "알 수 없는 kind")
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO saved_items (kind, ref, url, title, subtitle, note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (body.kind, body.ref, body.url, body.title, body.subtitle, body.note))
    conn.commit()
    row = conn.execute(
        "SELECT * FROM saved_items WHERE kind=? AND ref=?", (body.kind, body.ref)).fetchone()
    conn.close()
    return SavedItem(**dict(row))


@router.patch("/{item_id}", response_model=SavedItem)
def update_note(item_id: int, body: NoteRequest):
    conn = get_connection()
    row = conn.execute("SELECT id FROM saved_items WHERE id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "저장 항목을 찾을 수 없습니다")
    conn.execute("UPDATE saved_items SET note=? WHERE id=?", (body.note, item_id))
    conn.commit()
    updated = conn.execute("SELECT * FROM saved_items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    return SavedItem(**dict(updated))


@router.delete("/{item_id}", status_code=204)
def remove_saved(item_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM saved_items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
