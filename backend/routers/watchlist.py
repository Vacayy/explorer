from fastapi import APIRouter, HTTPException
from database import get_connection
from models.watchlist import WatchlistCreate, WatchlistUpdate, WatchlistResponse

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _enrich_row(row: dict) -> dict:
    conn = get_connection()
    price_row = conn.execute(
        """
        SELECT close, market_cap FROM stock_prices
        WHERE stock_code = ?
        ORDER BY trade_date DESC LIMIT 1
        """,
        (row["stock_code"],),
    ).fetchone()
    conn.close()

    latest_close = price_row["close"] if price_row else None
    latest_market_cap = price_row["market_cap"] if price_row else None

    target_price = row.get("target_price")
    if target_price is not None and latest_close:
        gap_pct = (target_price - latest_close) / latest_close * 100
    else:
        gap_pct = None

    return {**row, "latest_close": latest_close, "latest_market_cap": latest_market_cap, "gap_pct": gap_pct}


@router.get("", response_model=list[WatchlistResponse])
def list_watchlist():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM watchlist ORDER BY id").fetchall()
    conn.close()
    return [_enrich_row(dict(r)) for r in rows]


@router.post("", response_model=WatchlistResponse)
def create_watchlist(body: WatchlistCreate):
    conn = get_connection()
    company = conn.execute(
        "SELECT corp_code, corp_name FROM companies WHERE stock_code = ?",
        (body.stock_code,),
    ).fetchone()
    if not company:
        conn.close()
        raise HTTPException(404, "Company not found")

    corp_code = company["corp_code"]
    corp_name = company["corp_name"]

    existing = conn.execute(
        "SELECT id FROM watchlist WHERE stock_code = ?", (body.stock_code,)
    ).fetchone()

    if existing:
        updates = {}
        if body.conviction is not None:
            updates["conviction"] = body.conviction
        if body.target_price is not None:
            updates["target_price"] = body.target_price
        if body.thesis is not None:
            updates["thesis"] = body.thesis

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE watchlist SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
                list(updates.values()) + [existing["id"]],
            )
            conn.commit()

        row = conn.execute("SELECT * FROM watchlist WHERE id = ?", (existing["id"],)).fetchone()
        conn.close()
        return _enrich_row(dict(row))

    cur = conn.execute(
        """
        INSERT INTO watchlist (stock_code, corp_code, corp_name, conviction, target_price, thesis)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (body.stock_code, corp_code, corp_name, body.conviction, body.target_price, body.thesis),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM watchlist WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return _enrich_row(dict(row))


@router.put("/{item_id}", response_model=WatchlistResponse)
def update_watchlist(item_id: int, body: WatchlistUpdate):
    conn = get_connection()
    existing = conn.execute("SELECT * FROM watchlist WHERE id = ?", (item_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "Watchlist item not found")

    updates = {}
    if body.conviction is not None:
        updates["conviction"] = body.conviction
    if body.target_price is not None:
        updates["target_price"] = body.target_price
    if body.thesis is not None:
        updates["thesis"] = body.thesis

    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE watchlist SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
            list(updates.values()) + [item_id],
        )
        conn.commit()

    row = conn.execute("SELECT * FROM watchlist WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    return _enrich_row(dict(row))


@router.delete("/{item_id}")
def delete_watchlist(item_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM watchlist WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return {"ok": True}
