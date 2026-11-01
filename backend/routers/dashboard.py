"""홈 위젯 배치 저장 — 단일 사용자. 이름별 배치 한 벌(layouts)과 홈 메뉴(boards, 메뉴 하나 = 배치 하나)."""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Path

from database import get_connection
from models.dashboard import Board, BoardIn, BoardOrder, BoardPatch, Layout, LayoutBody, LayoutSummary

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
Name = Path(pattern=r"^[a-z0-9_-]{1,40}$")


@router.get("/layouts", response_model=list[LayoutSummary])
def list_layouts():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT name, layout_json, updated_at FROM dashboard_layouts ORDER BY name").fetchall()
    finally:
        conn.close()
    return [{"name": r["name"], "updated_at": r["updated_at"], "count": len(json.loads(r["layout_json"]))} for r in rows]


@router.get("/layouts/{name}", response_model=Layout)
def get_layout(name: str = Name):
    conn = get_connection()
    try:
        row = conn.execute("SELECT layout_json, updated_at FROM dashboard_layouts WHERE name=?", (name,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, "저장된 배치가 없습니다.")
    return {"name": name, "items": json.loads(row["layout_json"]), "updated_at": row["updated_at"]}


@router.put("/layouts/{name}", response_model=Layout)
def put_layout(body: LayoutBody, name: str = Name):
    items = [item.model_dump() for item in body.items]
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        conn.execute("INSERT INTO dashboard_layouts (name, layout_json, updated_at) VALUES (?,?,?) "
                     "ON CONFLICT(name) DO UPDATE SET layout_json=excluded.layout_json, updated_at=excluded.updated_at",
                     (name, json.dumps(items, ensure_ascii=False), updated_at))
        conn.commit()
    finally:
        conn.close()
    return {"name": name, "items": items, "updated_at": updated_at}



# ── 홈 메뉴(보드) — 메뉴 하나 = 위젯 배치 하나. 옮겨 다니는 건 화면 이동, 배치는 놓을 때마다 저장 ──

def _board(r) -> dict:
    return {"id": r["id"], "label": r["label"], "sort": r["sort"], "items": json.loads(r["layout_json"]), "updated_at": r["updated_at"]}


@router.get("/boards", response_model=list[Board])
def list_boards():
    conn = get_connection()
    try:
        return [_board(r) for r in conn.execute("SELECT * FROM home_boards ORDER BY sort, id")]
    finally:
        conn.close()


@router.post("/boards", response_model=Board)
def create_board(body: BoardIn):
    items = [item.model_dump() for item in body.items]
    conn = get_connection()
    try:
        cur = conn.execute("INSERT INTO home_boards (label, sort, layout_json) "
                           "VALUES (?, (SELECT COALESCE(MAX(sort), -1) + 1 FROM home_boards), ?)",
                           (body.label.strip(), json.dumps(items, ensure_ascii=False)))
        conn.commit()
        return _board(conn.execute("SELECT * FROM home_boards WHERE id=?", (cur.lastrowid,)).fetchone())
    finally:
        conn.close()


@router.put("/boards/order", response_model=list[Board])
def order_boards(body: BoardOrder):
    conn = get_connection()
    try:
        conn.executemany("UPDATE home_boards SET sort=? WHERE id=?", [(n, bid) for n, bid in enumerate(body.ids)])
        conn.commit()
        return [_board(r) for r in conn.execute("SELECT * FROM home_boards ORDER BY sort, id")]
    finally:
        conn.close()


@router.patch("/boards/{bid}", response_model=Board)
def update_board(bid: int, body: BoardPatch):
    sets: dict = {}
    if body.label is not None:
        sets["label"] = body.label.strip()
    if body.items is not None:
        sets["layout_json"] = json.dumps([item.model_dump() for item in body.items], ensure_ascii=False)
    conn = get_connection()
    try:
        if sets:
            conn.execute(f"UPDATE home_boards SET {', '.join(f'{k}=?' for k in sets)}, updated_at=datetime('now') WHERE id=?", (*sets.values(), bid))
            conn.commit()
        r = conn.execute("SELECT * FROM home_boards WHERE id=?", (bid,)).fetchone()
        if not r:
            raise HTTPException(404, "메뉴가 없습니다.")
        return _board(r)
    finally:
        conn.close()


@router.delete("/boards/{bid}")
def delete_board(bid: int):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM home_boards WHERE id=?", (bid,))
        conn.commit()
        return {"deleted": bid}
    finally:
        conn.close()
