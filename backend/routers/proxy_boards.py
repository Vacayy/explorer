"""프록시 보드 API (D-240, docs/specs/question-proxy.md '프록시 보드').

GET은 전부 LLM 0 — 어댑터가 원천 테이블을 읽는다. LLM은 POST /suggest(보드 만들 때 지표 제안, sonnet 1회)뿐이다.
"""
import secrets

from fastapi import APIRouter, HTTPException, Query, Response

from database import get_connection
from models.proxy_boards import (AdapterInfo, BoardCreate, BoardDetail, BoardPatch, BoardSummary, CatalogEntry, ItemAdd,
                                 ItemAdded, ItemOrder, SuggestReq, SuggestResp)
from pipeline import proxy_adapters as pa
from pipeline import proxy_boards as pb

router = APIRouter(prefix="/api/spine/proxy-boards", tags=["proxy-boards"])
BOARD_COLS = "id, name, description, question_id, narrative_id, group_id, created_at, updated_at"


def _board(conn, board_id: int):
    row = conn.execute(f"SELECT {BOARD_COLS} FROM proxy_boards WHERE id=?", (board_id,)).fetchone()
    if not row:
        raise HTTPException(404, "보드가 없습니다.")
    return row


def _summary(conn, row, items: list[dict]) -> dict:
    return {**dict(row), "item_count": len(items), "in_warn_count": sum(i["in_warn"] for i in items)}


# ── 어댑터 (항목 추가 UI) — /{board_id}보다 먼저 선언 ─────────────────────────

@router.get("/adapters", response_model=list[AdapterInfo])
def list_adapters():
    return [{"kind": a.kind, "label": a.label, "ref_format": a.ref_format, "description": a.description, "change_basis": a.basis}
            for a in pa.ADAPTERS.values()]


@router.get("/adapters/{kind}/catalog", response_model=list[CatalogEntry])
def adapter_catalog(kind: str, q: str | None = None, limit: int = Query(50, ge=1, le=500)):
    if kind not in pa.ADAPTERS:
        raise HTTPException(404, f"알 수 없는 어댑터 '{kind}'")
    conn = get_connection()
    try:
        return pa.catalog(conn, kind, q=q or None, limit=limit)
    finally:
        conn.close()


@router.post("/suggest", response_model=SuggestResp)
def suggest(body: SuggestReq):
    """보드 만들 때만 부른다(LLM 1회). GET 경로에서 호출하지 않는다."""
    from pipeline.enrich import llm_available
    if not llm_available():
        raise HTTPException(503, "LLM을 쓸 수 없어 지표 제안을 만들 수 없습니다. 카탈로그에서 직접 고르세요.")
    conn = get_connection()
    try:
        return pb.suggest(conn, body.topic.strip(), body.question_id, body.narrative_id)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(502, f"지표 제안 응답을 읽지 못했습니다: {e}")
    finally:
        conn.close()


# ── 보드 CRUD ───────────────────────────────────────────────────────────────

@router.get("", response_model=list[BoardSummary])
@router.get("/", response_model=list[BoardSummary], include_in_schema=False)
def list_boards():
    conn = get_connection()
    try:
        rows = conn.execute(f"SELECT {BOARD_COLS} FROM proxy_boards ORDER BY updated_at DESC, id DESC").fetchall()
        return [_summary(conn, r, pb.board_items(conn, r["id"])) for r in rows]
    finally:
        conn.close()


@router.post("", response_model=BoardSummary, status_code=201)
@router.post("/", response_model=BoardSummary, status_code=201, include_in_schema=False)
def create_board(body: BoardCreate):
    conn = get_connection()
    try:
        name = body.name.strip()
        if conn.execute("SELECT 1 FROM proxy_boards WHERE name=?", (name,)).fetchone():
            raise HTTPException(409, f"같은 이름의 보드가 있습니다: {name}")
        cur = conn.execute("INSERT INTO proxy_boards (name, description, question_id, narrative_id, group_id) VALUES (?,?,?,?,?)",
                           (name, body.description, body.question_id, body.narrative_id, body.group_id))
        conn.commit()
        return _summary(conn, _board(conn, cur.lastrowid), [])
    finally:
        conn.close()


@router.get("/{board_id}", response_model=BoardDetail)
def get_board(board_id: int, days: int | None = Query(None, ge=7, le=3650)):
    """보드 상세 — 항목별 최신값·변화·주의 여부·시계열. LLM 0. days 없으면 어댑터별 기본 길이(일간 3개월, 월간 13개월 등)."""
    conn = get_connection()
    try:
        row = _board(conn, board_id)
        items = pb.board_items(conn, board_id, days)
        return {**_summary(conn, row, items), "items": items}
    finally:
        conn.close()


@router.patch("/{board_id}", response_model=BoardSummary)
def patch_board(board_id: int, body: BoardPatch):
    fields = body.model_dump(exclude_unset=True)
    conn = get_connection()
    try:
        _board(conn, board_id)
        if "name" in fields:
            if fields["name"] is None:
                raise HTTPException(422, "이름은 비울 수 없습니다.")
            fields["name"] = fields["name"].strip()
            if conn.execute("SELECT 1 FROM proxy_boards WHERE name=? AND id!=?", (fields["name"], board_id)).fetchone():
                raise HTTPException(409, f"같은 이름의 보드가 있습니다: {fields['name']}")
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE proxy_boards SET {sets}, updated_at=datetime('now') WHERE id=?", (*fields.values(), board_id))
            conn.commit()
        row = _board(conn, board_id)
        return _summary(conn, row, pb.board_items(conn, board_id))
    finally:
        conn.close()


def _drop_orphan_proxies(conn, proxy_ids: list[int]) -> None:
    """보드가 만든 결정적 어댑터 지표가 어느 보드에도 없으면 지운다(기존 질문 프록시는 건드리지 않는다)."""
    for pid in proxy_ids:
        conn.execute("DELETE FROM proxy_registry WHERE id=? AND adapter IS NOT NULL AND sub_question_id IS NULL "
                     "AND NOT EXISTS (SELECT 1 FROM proxy_board_items WHERE proxy_id=?)", (pid, pid))


@router.delete("/{board_id}", status_code=204)
def delete_board(board_id: int):
    conn = get_connection()
    try:
        _board(conn, board_id)
        pids = [r[0] for r in conn.execute("SELECT proxy_id FROM proxy_board_items WHERE board_id=?", (board_id,))]
        conn.execute("DELETE FROM proxy_board_items WHERE board_id=?", (board_id,))
        conn.execute("DELETE FROM proxy_boards WHERE id=?", (board_id,))
        _drop_orphan_proxies(conn, pids)
        conn.commit()
    finally:
        conn.close()
    return Response(status_code=204)


# ── 항목 ────────────────────────────────────────────────────────────────────

def _new_proxy(conn, body: ItemAdd) -> int:
    """새 정의 → 어댑터·참조 검증 → 보드가 소유하는 proxy_registry 행.
    transcript·corpus 참조도 새 행(adapter_ref가 기존 프록시를 가리킴)으로 만든다 — 보드의 이름·주의 방향을 기존
    질문 프록시에 덮어쓰지 않고, 버리지도 않는다."""
    if not body.label or not body.label.strip():
        raise HTTPException(422, "새 지표에는 label이 필요합니다.")
    if body.adapter not in pa.ADAPTERS:
        raise HTTPException(422, f"알 수 없는 어댑터 '{body.adapter}' — 가능: {', '.join(pa.ADAPTERS)}")
    meta = pa.describe(conn, body.adapter_ref or "", body.adapter)
    if not meta:
        raise HTTPException(422, f"'{body.adapter_ref}'는 {body.adapter} 원천에 없는 참조입니다.")
    cur = conn.execute(
        "INSERT INTO proxy_registry (key, label, unit, adapter, adapter_ref, warn_direction, rationale) VALUES (?,?,?,?,?,?,?)",
        (f"adp:{meta['ref']}:{secrets.token_hex(3)}", body.label.strip(), body.unit or meta["unit"], body.adapter, meta["ref"],
         body.warn_direction, body.rationale))
    return cur.lastrowid


@router.post("/{board_id}/items", response_model=ItemAdded, status_code=201)
def add_item(board_id: int, body: ItemAdd):
    conn = get_connection()
    try:
        _board(conn, board_id)
        if body.proxy_id is not None:
            if any(v is not None for v in (body.label, body.adapter, body.adapter_ref)):
                raise HTTPException(422, "proxy_id와 새 정의(label·adapter·adapter_ref)는 함께 보낼 수 없습니다.")
            if not conn.execute("SELECT 1 FROM proxy_registry WHERE id=?", (body.proxy_id,)).fetchone():
                raise HTTPException(422, f"프록시 {body.proxy_id}가 없습니다.")
            proxy_id = body.proxy_id
        else:
            proxy_id = _new_proxy(conn, body)
        if conn.execute("SELECT 1 FROM proxy_board_items WHERE board_id=? AND proxy_id=?", (board_id, proxy_id)).fetchone():
            conn.rollback()
            raise HTTPException(409, "이미 보드에 있는 지표입니다.")
        position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM proxy_board_items WHERE board_id=?", (board_id,)).fetchone()[0]
        conn.execute("INSERT INTO proxy_board_items (board_id, proxy_id, position) VALUES (?,?,?)", (board_id, proxy_id, position))
        conn.execute("UPDATE proxy_boards SET updated_at=datetime('now') WHERE id=?", (board_id,))
        conn.commit()
        return {"proxy_id": proxy_id, "position": position}
    finally:
        conn.close()


@router.delete("/{board_id}/items/{proxy_id}", status_code=204)
def remove_item(board_id: int, proxy_id: int):
    conn = get_connection()
    try:
        _board(conn, board_id)
        cur = conn.execute("DELETE FROM proxy_board_items WHERE board_id=? AND proxy_id=?", (board_id, proxy_id))
        if not cur.rowcount:
            raise HTTPException(404, "보드에 없는 지표입니다.")
        _drop_orphan_proxies(conn, [proxy_id])
        conn.execute("UPDATE proxy_boards SET updated_at=datetime('now') WHERE id=?", (board_id,))
        conn.commit()
    finally:
        conn.close()
    return Response(status_code=204)


@router.put("/{board_id}/items/order", status_code=204)
def reorder_items(board_id: int, body: ItemOrder):
    conn = get_connection()
    try:
        _board(conn, board_id)
        current = {r[0] for r in conn.execute("SELECT proxy_id FROM proxy_board_items WHERE board_id=?", (board_id,))}
        if len(body.proxy_ids) != len(set(body.proxy_ids)) or set(body.proxy_ids) != current:
            raise HTTPException(422, "proxy_ids는 보드의 현재 지표 전체를 한 번씩 담아야 합니다.")
        conn.executemany("UPDATE proxy_board_items SET position=? WHERE board_id=? AND proxy_id=?",
                         [(i, board_id, pid) for i, pid in enumerate(body.proxy_ids)])
        conn.execute("UPDATE proxy_boards SET updated_at=datetime('now') WHERE id=?", (board_id,))
        conn.commit()
    finally:
        conn.close()
    return Response(status_code=204)
