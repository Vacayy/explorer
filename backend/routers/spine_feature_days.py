"""종목 특징일 API — 급등락일 감지 + 원인 조사 (pipeline/feature_days)."""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/spine/stock", tags=["spine"])


class FeatureDay(BaseModel):
    date: str
    ret_pct: float
    volume_ratio: float | None
    direction: str          # up | down
    note: str | None
    note_status: str | None  # ok | no_docs | failed | None(미조사)


class FeatureDaysResponse(BaseModel):
    stock_code: str
    days: list[FeatureDay]


@router.get("/{stock_code}/feature-days", response_model=FeatureDaysResponse)
def feature_days(stock_code: str):
    """마커용 특징일 목록 — LLM 없음 (감지만, note는 캐시된 것만)."""
    from pipeline.feature_days import detect_feature_days
    return {"stock_code": stock_code, "days": detect_feature_days(stock_code)}


class DayDoc(BaseModel):
    id: int
    title: str


class DayExplain(BaseModel):
    note: str | None
    status: str
    docs: list[DayDoc]


@router.post("/{stock_code}/feature-days/{day}/explain", response_model=DayExplain)
def explain_feature_day(stock_code: str, day: str):
    """마커 클릭 시 원인 조사 — 캐시 우선, 없으면 haiku 1콜 (게으른)."""
    from pipeline.feature_days import explain_day
    return explain_day(stock_code, day)
