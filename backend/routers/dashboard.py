"""홈 위젯 배치 저장 — 단일 사용자, 이름별 한 벌. 없으면 404 → FE가 기본 배치를 쓴다."""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Path

from database import get_connection
from models.dashboard import Layout, LayoutBody, LayoutSummary, Preset, PresetIn, PresetPatch

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



# ── 내 프리셋 — 지금 배치를 이름 붙여 저장·불러오기(기본 프리셋 대체) ──────────────

def _preset(r) -> dict:
    return {"id": r["id"], "board": r["board"], "label": r["label"], "items": json.loads(r["layout_json"]), "updated_at": r["updated_at"]}


@router.get("/presets", response_model=list[Preset])
def list_presets(board: str = "home-v2"):
    conn = get_connection()
    try:
        return [_preset(r) for r in conn.execute("SELECT * FROM dashboard_presets WHERE board=? ORDER BY id", (board,))]
    finally:
        conn.close()


@router.post("/presets", response_model=Preset)
def create_preset(body: PresetIn):
    items = [item.model_dump() for item in body.items]
    conn = get_connection()
    try:
        cur = conn.execute("INSERT INTO dashboard_presets (board, label, layout_json) VALUES (?,?,?)",
                           (body.board, body.label.strip(), json.dumps(items, ensure_ascii=False)))
        conn.commit()
        return _preset(conn.execute("SELECT * FROM dashboard_presets WHERE id=?", (cur.lastrowid,)).fetchone())
    finally:
        conn.close()


@router.patch("/presets/{pid}", response_model=Preset)
def update_preset(pid: int, body: PresetPatch):
    sets: dict = {}
    if body.label is not None:
        sets["label"] = body.label.strip()
    if body.items is not None:
        sets["layout_json"] = json.dumps([item.model_dump() for item in body.items], ensure_ascii=False)
    conn = get_connection()
    try:
        if sets:
            conn.execute(f"UPDATE dashboard_presets SET {', '.join(f'{k}=?' for k in sets)}, updated_at=datetime('now') WHERE id=?", (*sets.values(), pid))
            conn.commit()
        r = conn.execute("SELECT * FROM dashboard_presets WHERE id=?", (pid,)).fetchone()
        if not r:
            raise HTTPException(404, "프리셋이 없습니다.")
        return _preset(r)
    finally:
        conn.close()


@router.delete("/presets/{pid}")
def delete_preset(pid: int):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM dashboard_presets WHERE id=?", (pid,))
        conn.commit()
        return {"deleted": pid}
    finally:
        conn.close()
