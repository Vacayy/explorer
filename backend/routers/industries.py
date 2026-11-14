"""관심 산업 그룹(industry_groups/members) — 목록과 멤버 편입만 남았다.

그룹 관리 화면(유니버스·산업군 지도)은 지웠다(D-319). 남은 호출처: 인과 그래프 수혜 종목 → 그룹 편입(CausalDetail).
"""
from fastapi import APIRouter, HTTPException
from database import get_connection
from pydantic import BaseModel

router = APIRouter(prefix="/api/industries", tags=["industries"])


@router.get("/")
def list_groups():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, description FROM industry_groups ORDER BY name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


class MemberAdd(BaseModel):
    stock_code: str
    category: str


@router.post("/{group_id}/members")
def add_member(group_id: int, body: MemberAdd):
    conn = get_connection()
    exists = conn.execute("SELECT id FROM industry_groups WHERE id = ?", (group_id,)).fetchone()
    if not exists:
        conn.close()
        raise HTTPException(404, "Group not found")

    conn.execute(
        "INSERT OR REPLACE INTO industry_members (group_id, stock_code, category) VALUES (?, ?, ?)",
        (group_id, body.stock_code, body.category),
    )
    conn.commit()
    conn.close()
    return {"ok": True}
