from fastapi import APIRouter, Query
from database import get_connection
from models.company import CompanyResponse

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("/search", response_model=list[CompanyResponse])
def search_companies(q: str = Query(..., min_length=1), limit: int = 20):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT corp_code, corp_name, stock_code, market, sector
        FROM companies
        WHERE stock_code IS NOT NULL
          AND (corp_name LIKE ? OR stock_code LIKE ?)
        ORDER BY
          CASE WHEN corp_name = ? THEN 0
               WHEN corp_name LIKE ? THEN 1
               ELSE 2
          END
        LIMIT ?
        """,
        (f"%{q}%", f"%{q}%", q, f"{q}%", limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/{stock_code}", response_model=CompanyResponse)
def get_company(stock_code: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT corp_code, corp_name, stock_code, market, sector FROM companies WHERE stock_code = ?",
        (stock_code,),
    ).fetchone()
    conn.close()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Company not found")
    return dict(row)
