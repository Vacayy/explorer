"""회사채 스프레드 API (D-230, docs/specs/credit-spreads.md) — 저장분 읽기만, LLM 0."""
from fastapi import APIRouter, Query

from database import get_connection
from models.credit import CreditHistory, CreditTable
from pipeline import credit_spreads as cs

router = APIRouter(prefix="/api/spine/credit", tags=["spine"])


@router.get("", response_model=CreditTable)
def get_table():
    conn = get_connection()
    try:
        return cs.table(conn)
    finally:
        conn.close()


@router.get("/history", response_model=CreditHistory)
def get_history(tickers: str = Query(..., max_length=200), days: int = Query(1000, ge=30, le=3000)):
    conn = get_connection()
    try:
        return cs.history(conn, [t for t in tickers.split(",") if t][:8], days)
    finally:
        conn.close()
