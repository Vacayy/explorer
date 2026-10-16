"""홈 위젯 배치 저장 — 단일 사용자, 이름별 한 벌. 없으면 404 → FE가 기본 배치를 쓴다."""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Path

from database import get_connection
from models.dashboard import Layout, LayoutBody, LayoutSummary

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
