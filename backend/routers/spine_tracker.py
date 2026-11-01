"""종목 추적 위젯 API (docs/specs/stock-tracker.md) — 카드 조합(LLM 0)·원칙 조건 CRUD·수급 즉시 수집."""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Path

from database import get_connection
from models.tracker import TrackerCondition, TrackerConditionIn, TrackerConditionPatch, TrackerView

router = APIRouter(prefix="/api/spine/tracker", tags=["spine"])
Code = Path(pattern=r"^[0-9A-Z]{6}$")


def _check(conn, code: str) -> None:
    if not conn.execute("SELECT 1 FROM companies WHERE stock_code=?", (code,)).fetchone():
        raise HTTPException(404, f"알 수 없는 종목: {code}")


@router.get("/{code}", response_model=TrackerView)
def tracker_view(code: str = Code):
    from pipeline.stock_tracker import read
    conn = get_connection()
    try:
        _check(conn, code)
        return read(conn, code)
    finally:
        conn.close()


@router.post("/{code}/prepare")
def tracker_prepare(background: BackgroundTasks, code: str = Code):
    """위젯을 막 놓았을 때 — 수급 30일을 바로 받는다(다음 정기 수집을 기다리지 않게)"""
    from pipeline.flows import collect_flows
    background.add_task(collect_flows, [code])
    return {"queued": True}


@router.post("/{code}/conditions", response_model=TrackerCondition)
def condition_add(body: TrackerConditionIn, code: str = Code):
    from pipeline.stock_tracker import ensure
    if body.kind.startswith("price_") and not body.level:
        raise HTTPException(422, "가격 조건에는 기준가가 필요합니다")
    if body.kind.endswith("_ma") and not body.ma:
        raise HTTPException(422, "이평선 조건에는 N일이 필요합니다")
    conn = get_connection()
    try:
        _check(conn, code)
        ensure(conn)
        cur = conn.execute("INSERT INTO tracker_conditions (stock_code, role, kind, level, ma, label, note) VALUES (?,?,?,?,?,?,?)",
                           (code, body.role, body.kind, body.level, body.ma, body.label, body.note))
        conn.commit()
        return dict(conn.execute("SELECT * FROM tracker_conditions WHERE id=?", (cur.lastrowid,)).fetchone())
    finally:
        conn.close()


@router.patch("/conditions/{cid}", response_model=TrackerCondition)
def condition_patch(cid: int, body: TrackerConditionPatch):
    sets = {k: v for k, v in body.model_dump().items() if v is not None}
    conn = get_connection()
    try:
        if sets:
            conn.execute(f"UPDATE tracker_conditions SET {', '.join(f'{k}=?' for k in sets)}, updated_at=datetime('now') WHERE id=?", (*sets.values(), cid))
            conn.commit()
        r = conn.execute("SELECT * FROM tracker_conditions WHERE id=?", (cid,)).fetchone()
        if not r:
            raise HTTPException(404, "조건 없음")
        return dict(r)
    finally:
        conn.close()


@router.delete("/conditions/{cid}")
def condition_delete(cid: int):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM tracker_conditions WHERE id=?", (cid,))
        conn.commit()
        return {"deleted": cid}
    finally:
        conn.close()
