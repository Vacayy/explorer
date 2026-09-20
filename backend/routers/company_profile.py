"""웹 조사 기업 개요 보고서 API (docs/specs/company-research.md §웹 조사 레인, D-188)."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from pipeline import company_profile as cp

router = APIRouter(prefix="/api/spine/company-profile", tags=["spine"])


class ProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str | None = Field(default=None, max_length=600)
    force: bool = False


def _company(conn, code: str):
    row = conn.execute("SELECT corp_name, sector FROM companies WHERE stock_code=?", (code,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "등록되지 않은 종목 코드입니다.")
    return row["corp_name"], row["sector"]


@router.get("/{code}")
def get_profile(code: str):
    conn = cp.connect()
    try:
        _company(conn, code)
        profile = cp.latest_profile(conn, code)
    finally:
        conn.close()
    return {"profile": profile, "reuse_hours": cp.REUSE_HOURS}


@router.post("/{code}")
def build_profile(code: str, body: ProfileRequest):
    """사용자 클릭 1회 = 웹 조사 모델 1콜(24시간 내 보고서는 재사용, force로 재생성)."""
    conn = cp.connect()
    try:
        name, sector = _company(conn, code)
    finally:
        conn.close()
    try:
        profile, reused = cp.ensure_profile(code, name, sector, body.reason, force=body.force)
    except cp.ProfileUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:  # 모델 실행·네트워크 오류는 사용자에게 그대로 보인다(조용한 폴백 금지)
        raise HTTPException(502, f"웹 조사를 마치지 못했습니다: {str(exc)[:200]}") from exc
    return {"profile": profile, "reused": reused, "reuse_hours": cp.REUSE_HOURS}
