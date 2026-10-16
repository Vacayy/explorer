"""차트 구조 그리기 API (docs/specs/chart-structure.md, D-195). 모델 호출 0."""
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from database import get_connection
from pipeline.chart_structure import FITS, KINDS, StructureUnavailable, draw, interpret

router = APIRouter(prefix="/api/spine/chart-structure", tags=["spine"])


class InterpretRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


@router.post("/interpret")
def interpret_question(body: InterpretRequest):
    conn = get_connection()
    try:
        return interpret(conn, body.question)
    finally:
        conn.close()


@router.get("/{code}")
def chart_structure(code: str, market: Literal["kr", "us"] = Query("kr"), kind: str = Query("channel"),
                    window: str = Query("ytd", max_length=21), swing: int = Query(5, ge=2, le=30), fit: str = Query("two_point")):
    code = code.upper() if market == "us" else code
    if not re.fullmatch(r"[0-9A-Z][0-9A-Z.\-]{0,9}", code):
        raise HTTPException(404, "종목 코드 형식이 아닙니다.")
    if kind not in KINDS or fit not in FITS:
        raise HTTPException(422, "지원하지 않는 구조 또는 적합 방식입니다.")
    conn = get_connection()
    try:
        name = None
        if market == "kr":
            row = conn.execute("SELECT corp_name FROM companies WHERE stock_code=? LIMIT 1", (code,)).fetchone()
            name = row["corp_name"] if row else None
        else:
            from pipeline.us_data import resolve_us
            resolved = resolve_us(conn, code)
            name = resolved[1] if resolved else None
        try:
            result = draw(conn, code, market, kind, window, swing, fit)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (StructureUnavailable, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
    finally:
        conn.close()
    return {"name": name or code, **result}
