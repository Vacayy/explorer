"""개인 투자 열기 응답 모델 (D-231)."""
from pydantic import BaseModel


class RetailRegime(BaseModel):
    key: str                           # deleveraging | leverage_led | churn | broad_inflow | neutral
    label: str
    reasons: list[str]                 # 조건별 값·문턱


class RetailMetric(BaseModel):
    key: str
    label: str
    unit: str                          # rate(비율 변화) | ratio(비중) | krw(원)
    value: float | None
    pctile: float | None               # 과거 5년 백분위(그날 이전 값만)
    pctile_change: float | None        # 20영업일 전 대비 백분위 변화


class RetailSummary(BaseModel):
    as_of: str | None
    regime: RetailRegime | None
    metrics: list[RetailMetric]
    levels: dict
    krx_configured: bool
    accounts_available: bool


class RetailSnapshot(BaseModel):
    episode: str
    date: str
    name: str
    regime: RetailRegime
    metrics: list[RetailMetric]
    levels: dict
