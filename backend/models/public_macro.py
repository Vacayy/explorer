from typing import Literal
from pydantic import BaseModel


class MacroSource(BaseModel):
    series_id: str
    publisher: str
    url: str
    as_of: str | None


class PublicMacroIndicator(BaseModel):
    key: str
    label: str
    group: str
    group_label: str
    fmt: Literal['pct', 'num', 'usd', 'trillion_b']
    as_of: str
    value: float
    change_pct: float | None
    series: list[float]
    dated_series: list[tuple[str, float]]
    comparison_date: str | None
    comparison_observations: int
    sources: list[MacroSource]


class MacroCoverage(BaseModel):
    key: str
    label: str
    status: Literal['available','missing','source_review_pending','invalid']


class PublicMacroResponse(BaseModel):
    as_of: str | None
    items: list[PublicMacroIndicator]
    coverage: list[MacroCoverage]
