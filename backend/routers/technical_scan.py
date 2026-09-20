"""기업 페이지 '기술적 분석' 스캔 API (docs/specs/market-strategies.md §기술적 분석 스캔, D-190)."""
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from database import get_connection
from pipeline.technical_scan import scan_company

router = APIRouter(prefix="/api/spine/technical-scan", tags=["spine"])


@router.get("/{code}")
def technical_scan(code: str, market: Literal["kr", "us"] = Query("kr"), within: int = Query(5, ge=1, le=60)):
    code = code.upper() if market == "us" else code
    if not re.fullmatch(r"[0-9A-Z][0-9A-Z.\-]{0,9}", code):
        raise HTTPException(404, "종목 코드 형식이 아닙니다.")
    conn = get_connection()
    try:
        result = scan_company(conn, code, market, within)
    finally:
        conn.close()
    if result["sessions"] == 0 if "sessions" in result else not result["as_of"]:
        raise HTTPException(404, "저장된 시세가 없는 종목입니다.")
    return result
