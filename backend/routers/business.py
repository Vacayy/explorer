from fastapi import APIRouter, Query, HTTPException
from database import get_connection
from pydantic import BaseModel

router = APIRouter(prefix="/api/business", tags=["business"])


class SegmentCreate(BaseModel):
    bsns_year: int
    segment_type: str  # 'division' or 'region'
    segment_name: str
    revenue: float | None = None
    ratio: float | None = None


class SegmentUpdate(BaseModel):
    revenue: float | None = None
    ratio: float | None = None


@router.get("/{stock_code}/segments")
def get_segments(
    stock_code: str,
    segment_type: str = Query("division", pattern="^(division|region)$"),
    years: int = Query(5, ge=1, le=20),
):
    conn = get_connection()
    corp_row = conn.execute(
        "SELECT corp_code FROM companies WHERE stock_code = ?", (stock_code,)
    ).fetchone()
    if not corp_row:
        conn.close()
        raise HTTPException(404, "Company not found")

    from datetime import datetime
    current_year = datetime.now().year
    start_year = current_year - years

    rows = conn.execute(
        """
        SELECT id, corp_code, bsns_year, segment_type, segment_name, revenue, ratio
        FROM business_segments
        WHERE corp_code = ? AND segment_type = ? AND bsns_year >= ? AND reprt_code = '11011'
        ORDER BY bsns_year, segment_name
        """,
        (corp_row["corp_code"], segment_type, start_year),
    ).fetchall()
    conn.close()
    return {"items": [dict(r) for r in rows]}


@router.post("/{stock_code}/segments")
def create_segment(stock_code: str, body: SegmentCreate):
    conn = get_connection()
    corp_row = conn.execute(
        "SELECT corp_code FROM companies WHERE stock_code = ?", (stock_code,)
    ).fetchone()
    if not corp_row:
        conn.close()
        raise HTTPException(404, "Company not found")

    conn.execute(
        """
        INSERT OR REPLACE INTO business_segments
        (corp_code, bsns_year, reprt_code, segment_type, segment_name, revenue, ratio)
        VALUES (?, ?, '11011', ?, ?, ?, ?)
        """,
        (corp_row["corp_code"], body.bsns_year, body.segment_type, body.segment_name, body.revenue, body.ratio),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.put("/segments/{segment_id}")
def update_segment(segment_id: int, body: SegmentUpdate):
    conn = get_connection()
    existing = conn.execute("SELECT * FROM business_segments WHERE id = ?", (segment_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "Segment not found")

    conn.execute(
        "UPDATE business_segments SET revenue = ?, ratio = ? WHERE id = ?",
        (body.revenue if body.revenue is not None else existing["revenue"],
         body.ratio if body.ratio is not None else existing["ratio"],
         segment_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.delete("/segments/{segment_id}")
def delete_segment(segment_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM business_segments WHERE id = ?", (segment_id,))
    conn.commit()
    conn.close()
    return {"ok": True}
