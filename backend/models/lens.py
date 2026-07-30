"""투자 렌즈 API 스키마 (docs/specs/investor-lens.md)."""
from pydantic import BaseModel


class LensReading(BaseModel):
    lens_type: str                     # value | trend
    status: str                        # cached | fresh | empty | unavailable | failed
    body: str | None = None            # 원칙에 비춘 판독 (마크다운)
    stance: str | None = None          # value: 강|중|약 (미래 확신 강도) / trend: 초입|진행|성숙|훼손
    signals: list[str] = []            # 역추적용 근거
    created_at: str | None = None
    stale: bool = False


class Quadrant(BaseModel):
    value_axis: str        # 강|중|약 (가치 확신)
    trend_axis: str        # 초입|진행|성숙|훼손 (추세 위치)
    cell: str              # 기회 | 늦은 진입 | 과열 경고 | 회피
    note: str


class LensBundle(BaseModel):
    stock_code: str
    value: LensReading | None = None
    trend: LensReading | None = None
    quadrant: Quadrant | None = None   # 두 렌즈 stance로 계산(LLM 0) — 둘 다 있을 때만
