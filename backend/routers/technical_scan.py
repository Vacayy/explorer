"""기업 페이지 '기술적 분석' 스캔 API (docs/specs/market-strategies.md §기술적 분석 스캔, D-190) + AI 해설 (D-191)."""
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from database import get_connection
from pipeline.technical_commentary import CommentaryUnavailable, explain, latest
from pipeline.technical_scan import load_rows, scan_company

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


def _code(code: str, market: str) -> str:
    code = code.upper() if market == "us" else code
    if not re.fullmatch(r"[0-9A-Z][0-9A-Z.\-]{0,9}", code):
        raise HTTPException(404, "종목 코드 형식이 아닙니다.")
    return code


@router.get("/{code}/commentary")
def get_commentary(code: str, market: Literal["kr", "us"] = Query("kr"), within: int = Query(5, ge=1, le=60)):
    """저장된 해설만 돌려준다 (기준일·범위가 같을 때). 없으면 404 — 모델을 부르지 않는다."""
    code = _code(code, market)
    conn = get_connection()
    try:
        rows = load_rows(conn, code, market, limit=1)
        if not rows:
            raise HTTPException(404, "저장된 시세가 없는 종목입니다.")
        found = latest(conn, code, market, rows[-1]["date"], within)
    finally:
        conn.close()
    if not found:
        raise HTTPException(404, "저장된 해설이 없습니다.")
    return {"code": code, "market": market, "reused": True, **found}


@router.post("/{code}/commentary")
def create_commentary(code: str, market: Literal["kr", "us"] = Query("kr"), within: int = Query(5, ge=1, le=60),
                      force: bool = Query(False)):
    """버튼 1회 = 모델 1콜(도구 없음). 같은 종목·기준일·범위는 24시간 재사용."""
    from pipeline.market_analysis.model import ModelError
    code = _code(code, market)
    conn = get_connection()
    try:
        payload, reused = explain(conn, code, market, within, force=force)
    except CommentaryUnavailable as exc:
        raise HTTPException(422, str(exc)) from exc
    except ModelError as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        conn.close()
    return {"code": code, "market": market, "reused": reused, **payload}
