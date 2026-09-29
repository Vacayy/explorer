from typing import Literal
from pydantic import BaseModel


class RiskIndicator(BaseModel):
    key: str
    label: str
    unit: str
    source: str
    source_url: str
    value: float | None
    as_of: str | None
    fetched_at: str | None
    attempted_at: str | None
    error: str | None
    quality: Literal['fresh', 'missing', 'stale', 'error']
    lag_days: int | None
    points: list[tuple[str, float]]
    change_5: float | None
    change_20: float | None


class RiskSignal(BaseModel):
    status: Literal['unavailable', 'joint', 'watch', 'credit', 'rates', 'clear']
    label: str
    as_of: str | None
    rate_change_bp: float | None
    credit_change_bp: float | None
    consecutive: int
    common_observations: int
    rule_version: str
    reason: str


class RiskResponse(BaseModel):
    items: list[RiskIndicator]
    signal: RiskSignal
    expected_date: str
    generated_at: str
    calendar_note: str
    empty: bool


class RiskSnapshotItem(BaseModel):
    key: str
    status: Literal['cached', 'updated', 'error']
    rows: int
    error: str | None = None


class RiskSnapshotResponse(BaseModel):
    busy: bool
    results: list[RiskSnapshotItem]
