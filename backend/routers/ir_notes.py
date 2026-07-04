from fastapi import APIRouter, Query, HTTPException
from database import get_connection
from models.ir_note import IRNoteCreate, IRNoteUpdate, IRNoteResponse

router = APIRouter(prefix="/api/ir-notes", tags=["ir_notes"])


@router.get("/{stock_code}", response_model=list[IRNoteResponse])
def list_notes(
    stock_code: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1),
    memo_type: str | None = Query(None),
):
    conn = get_connection()
    corp_row = conn.execute(
        "SELECT corp_code FROM companies WHERE stock_code = ?", (stock_code,)
    ).fetchone()
    if not corp_row:
        conn.close()
        raise HTTPException(404, "Company not found")

    corp_code = corp_row["corp_code"]
    offset = (page - 1) * size
    if memo_type is not None:
        rows = conn.execute(
            """
            SELECT id, corp_code, title, content, memo_type, note_date, created_at, updated_at
            FROM ir_notes WHERE corp_code = ? AND memo_type = ?
            ORDER BY note_date DESC
            LIMIT ? OFFSET ?
            """,
            (corp_code, memo_type, size, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, corp_code, title, content, memo_type, note_date, created_at, updated_at
            FROM ir_notes WHERE corp_code = ?
            ORDER BY note_date DESC
            LIMIT ? OFFSET ?
            """,
            (corp_code, size, offset),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/{stock_code}", response_model=IRNoteResponse)
def create_note(stock_code: str, body: IRNoteCreate):
    conn = get_connection()
    corp_row = conn.execute(
        "SELECT corp_code FROM companies WHERE stock_code = ?", (stock_code,)
    ).fetchone()
    if not corp_row:
        conn.close()
        raise HTTPException(404, "Company not found")

    corp_code = corp_row["corp_code"]
    cur = conn.execute(
        """
        INSERT INTO ir_notes (corp_code, title, content, memo_type, note_date)
        VALUES (?, ?, ?, ?, ?)
        """,
        (corp_code, body.title, body.content, body.memo_type, body.note_date),
    )
    conn.commit()
    note_id = cur.lastrowid
    row = conn.execute(
        "SELECT * FROM ir_notes WHERE id = ?", (note_id,)
    ).fetchone()
    conn.close()
    return dict(row)


@router.put("/{note_id}", response_model=IRNoteResponse)
def update_note(note_id: int, body: IRNoteUpdate):
    conn = get_connection()
    existing = conn.execute("SELECT * FROM ir_notes WHERE id = ?", (note_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "Note not found")

    updates = {}
    if body.title is not None:
        updates["title"] = body.title
    if body.content is not None:
        updates["content"] = body.content
    if body.note_date is not None:
        updates["note_date"] = body.note_date
    if body.memo_type is not None:
        updates["memo_type"] = body.memo_type

    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE ir_notes SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
            list(updates.values()) + [note_id],
        )
        conn.commit()

    row = conn.execute("SELECT * FROM ir_notes WHERE id = ?", (note_id,)).fetchone()
    conn.close()
    return dict(row)


@router.delete("/{note_id}")
def delete_note(note_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM ir_notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()
    return {"ok": True}
