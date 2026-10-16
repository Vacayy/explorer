"""개인 투자 열기 API (D-231, docs/specs/retail-heat.md) — 저장분 계산만, LLM 0."""
from fastapi import APIRouter, Query

from database import get_connection
from models.retail import RetailSnapshot, RetailSummary
from pipeline import retail_heat as rh

router = APIRouter(prefix="/api/spine/retail", tags=["spine"])


@router.get("", response_model=RetailSummary)
def get_summary():
    conn = get_connection()
    try:
        return rh.summary(conn)
    finally:
        conn.close()


@router.get("/history")
def get_history(days: int = Query(1500, ge=60, le=10000)):
    """날짜별 신용융자·예탁금·KOSPI·거래대금과 주요 파생 지표·백분위."""
    conn = get_connection()
    try:
        return {"points": rh.history(conn, days)}
    finally:
        conn.close()


@router.get("/snapshots", response_model=list[RetailSnapshot])
def get_snapshots():
    conn = get_connection()
    try:
        return rh.snapshots(conn)
    finally:
        conn.close()
