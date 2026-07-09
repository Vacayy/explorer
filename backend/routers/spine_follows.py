"""엔티티 팔로우 CRUD — 섹터·테마(·기타 엔티티) 팔로우.

종목 팔로우는 기존 watchlist가 담당. 여기는 그래프 엔티티 일반.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/follows", tags=["spine"])


class FollowedEntity(BaseModel):
    entity_id: int
    type: str
    name: str


class FollowRequest(BaseModel):
    entity_id: int | None = None
    type: str | None = None   # entity_id 없으면 (type, name)으로 해석
    name: str | None = None


@router.get("", response_model=list[FollowedEntity])
def list_follows():
    conn = get_connection()
    rows = conn.execute("""
        SELECT e.id entity_id, e.type, e.name FROM follows f
        JOIN entities e ON f.entity_id = e.id ORDER BY f.created_at
    """).fetchall()
    conn.close()
    return [FollowedEntity(**dict(r)) for r in rows]


@router.post("", response_model=FollowedEntity, status_code=201)
def add_follow(body: FollowRequest):
    conn = get_connection()
    if body.entity_id:
        row = conn.execute("SELECT id, type, name FROM entities WHERE id=?", (body.entity_id,)).fetchone()
    elif body.type and body.name:
        row = conn.execute("SELECT id, type, name FROM entities WHERE type=? AND name=?",
                           (body.type, body.name)).fetchone()
    else:
        conn.close()
        raise HTTPException(400, "entity_id 또는 (type, name) 필요")
    if not row:
        conn.close()
        raise HTTPException(404, "엔티티를 찾을 수 없습니다")
    conn.execute("INSERT OR IGNORE INTO follows (entity_id) VALUES (?)", (row["id"],))
    conn.commit()
    conn.close()
    return FollowedEntity(entity_id=row["id"], type=row["type"], name=row["name"])


@router.delete("/{entity_id}", status_code=204)
def remove_follow(entity_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM follows WHERE entity_id=?", (entity_id,))
    conn.commit()
    conn.close()
