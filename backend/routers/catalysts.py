from fastapi import APIRouter, Query, HTTPException
from database import get_connection
from models.catalyst import CatalystCreate, CatalystUpdate, CatalystResponse
from datetime import date, timedelta

router = APIRouter(prefix="/api/catalysts", tags=["catalysts"])


@router.get("", response_model=list[CatalystResponse])
def list_catalysts(
    stock_code: str | None = Query(None),
    days: int = Query(90, ge=1),
):
    conn = get_connection()
    today = date.today().isoformat()
    past_cutoff = (date.today() - timedelta(days=7)).isoformat()
    future_cutoff = (date.today() + timedelta(days=days)).isoformat()

    if stock_code:
        rows = conn.execute(
            """
            SELECT c.id, c.stock_code, c.corp_code, co.corp_name,
                   c.event_type, c.event_date, c.title, c.description, c.created_at
            FROM catalysts c
            LEFT JOIN companies co ON c.corp_code = co.corp_code
            WHERE c.stock_code = ?
              AND c.event_date >= ? AND c.event_date <= ?
            ORDER BY c.event_date ASC
            """,
            (stock_code, past_cutoff, future_cutoff),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT c.id, c.stock_code, c.corp_code, co.corp_name,
                   c.event_type, c.event_date, c.title, c.description, c.created_at
            FROM catalysts c
            LEFT JOIN companies co ON c.corp_code = co.corp_code
            WHERE c.event_date >= ? AND c.event_date <= ?
            ORDER BY c.event_date ASC
            """,
            (past_cutoff, future_cutoff),
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


@router.post("", response_model=CatalystResponse)
def create_catalyst(body: CatalystCreate):
    conn = get_connection()
    corp_code = None
    if body.stock_code:
        row = conn.execute(
            "SELECT corp_code FROM companies WHERE stock_code = ?", (body.stock_code,)
        ).fetchone()
        if row:
            corp_code = row["corp_code"]

    cur = conn.execute(
        """
        INSERT INTO catalysts (stock_code, corp_code, event_type, event_date, title, description)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (body.stock_code, corp_code, body.event_type, body.event_date, body.title, body.description),
    )
    conn.commit()
    catalyst_id = cur.lastrowid
    row = conn.execute(
        """
        SELECT c.id, c.stock_code, c.corp_code, co.corp_name,
               c.event_type, c.event_date, c.title, c.description, c.created_at
        FROM catalysts c
        LEFT JOIN companies co ON c.corp_code = co.corp_code
        WHERE c.id = ?
        """,
        (catalyst_id,),
    ).fetchone()
    conn.close()
    return dict(row)


@router.put("/{catalyst_id}", response_model=CatalystResponse)
def update_catalyst(catalyst_id: int, body: CatalystUpdate):
    conn = get_connection()
    existing = conn.execute("SELECT * FROM catalysts WHERE id = ?", (catalyst_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "Catalyst not found")

    updates = {}
    if body.event_type is not None:
        updates["event_type"] = body.event_type
    if body.event_date is not None:
        updates["event_date"] = body.event_date
    if body.title is not None:
        updates["title"] = body.title
    if body.description is not None:
        updates["description"] = body.description

    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE catalysts SET {set_clause} WHERE id = ?",
            list(updates.values()) + [catalyst_id],
        )
        conn.commit()

    row = conn.execute(
        """
        SELECT c.id, c.stock_code, c.corp_code, co.corp_name,
               c.event_type, c.event_date, c.title, c.description, c.created_at
        FROM catalysts c
        LEFT JOIN companies co ON c.corp_code = co.corp_code
        WHERE c.id = ?
        """,
        (catalyst_id,),
    ).fetchone()
    conn.close()
    return dict(row)


@router.delete("/{catalyst_id}")
def delete_catalyst(catalyst_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM catalysts WHERE id = ?", (catalyst_id,))
    conn.commit()
    conn.close()
    return {"ok": True}
