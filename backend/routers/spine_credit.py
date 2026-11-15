"""회사채 스프레드 API (D-230, docs/specs/credit-spreads.md) — 저장분 읽기만, LLM 0."""
from fastapi import APIRouter, Query, Request

from database import get_connection
from models.credit import CreditHistory, CreditTable
from pipeline import credit_spreads as cs

router = APIRouter(prefix="/api/spine/credit", tags=["spine"])


@router.get("", response_model=CreditTable)
def get_table(request: Request):
    public = getattr(request.state, "public_access", False)
    from security.public_risk import risk_connection
    conn = risk_connection() if public else get_connection()
    try:
        return cs.read_table(conn) if public else cs.table(conn)
    finally:
        conn.close()


@router.get("/history", response_model=CreditHistory)
def get_history(request: Request, tickers: str = Query(..., max_length=200), days: int = Query(1000, ge=30, le=3000)):
    public = getattr(request.state, "public_access", False)
    from security.public_risk import risk_connection
    conn = risk_connection() if public else get_connection()
    try:
        return (cs.read_history if public else cs.history)(conn, [t for t in tickers.split(",") if t][:8], days)
    finally:
        conn.close()
