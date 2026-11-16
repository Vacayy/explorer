from fastapi import APIRouter, Query, Request
from database import get_connection
from security.public_financials import financial_connection
from models.company import CompanyResponse
from models.stock_price import StockPriceResponse

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("/search", response_model=list[CompanyResponse])
def search_companies(request: Request, q: str = Query(..., min_length=1, max_length=100), limit: int = Query(20, ge=1, le=50)):
    conn = financial_connection() if getattr(request.state, "public_access", False) else get_connection()
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
def get_company(request: Request, stock_code: str):
    conn = financial_connection() if getattr(request.state, "public_access", False) else get_connection()
    row = conn.execute(
        "SELECT corp_code, corp_name, stock_code, market, sector FROM companies WHERE stock_code = ?",
        (stock_code,),
    ).fetchone()
    conn.close()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Company not found")
    return dict(row)


@router.get("/{stock_code}/prices", response_model=StockPriceResponse)
def get_stored_company_prices(stock_code: str):
    from security.public_financials import stored_company_prices
    return stored_company_prices(stock_code)
