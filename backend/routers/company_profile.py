"""웹 조사 기업 개요 보고서 API (docs/specs/company-research.md §웹 조사 레인, D-188)."""
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from pipeline import company_profile as cp

router = APIRouter(prefix="/api/spine/company-profile", tags=["spine"])


class ProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str | None = Field(default=None, max_length=600)
    force: bool = False


def _company(conn, code: str, market: str):
    """(이름, 업종). 미국 티커는 transcript_follow·entities에서 이름만 찾고 없으면 티커를 그대로 쓴다."""
    if market == "us":
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", code):
            conn.close()
            raise HTTPException(404, "미국 티커 형식이 아닙니다.")
        from pipeline.us_data import resolve_us
        try:
            _, name = resolve_us(conn, code)
        except Exception:
            name = None
        return name or code, None
    row = conn.execute("SELECT corp_name, sector FROM companies WHERE stock_code=?", (code,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "등록되지 않은 종목 코드입니다.")
    return row["corp_name"], row["sector"]


@router.get("/{code}")
def get_profile(code: str, market: Literal["kr", "us"] = Query("kr")):
    code = code.upper() if market == "us" else code
    conn = cp.connect()
    try:
        _company(conn, code, market)
        profile = cp.latest_profile(conn, code)
    finally:
        conn.close()
    return {"profile": profile, "reuse_hours": cp.REUSE_HOURS, "market": market}


@router.post("/{code}")
def build_profile(code: str, body: ProfileRequest, market: Literal["kr", "us"] = Query("kr")):
    """사용자 클릭 1회 = 웹 조사 모델 1콜(24시간 내 보고서는 재사용, force로 재생성). 미국은 DART 단계 없이 웹만."""
    code = code.upper() if market == "us" else code
    conn = cp.connect()
    try:
        name, sector = _company(conn, code, market)
    finally:
        conn.close()
    try:
        profile, reused = cp.ensure_profile(code, name, sector, body.reason, force=body.force, market=market)
    except cp.ProfileUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:  # 모델 실행·네트워크 오류는 사용자에게 그대로 보인다(조용한 폴백 금지)
        raise HTTPException(502, f"웹 조사를 마치지 못했습니다: {str(exc)[:200]}") from exc
    return {"profile": profile, "reused": reused, "reuse_hours": cp.REUSE_HOURS, "market": market}
