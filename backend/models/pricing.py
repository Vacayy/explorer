from typing import Literal
from pydantic import BaseModel


class PricingPrice(BaseModel):
    key: str
    label: str
    unit: str
    value: float | None
    as_of: str | None
    chg_1w: float | None
    chg_4w: float | None
    mode: Literal['bp', 'pct', 'pt']


class PricingObservation(BaseModel):
    date: str
    stance: Literal['present', 'stronger', 'weaker', 'contested']
    evidence: str | None
    sources: list[dict]


class PricingClaim(BaseModel):
    id: int
    statement: str
    theme: str
    first_seen: str
    last_seen: str
    days_seen: int
    status: Literal['new', 'stronger', 'weaker', 'faded', 'ongoing', 'dormant']
    dates: list[tuple[str, str]]
    latest: PricingObservation | None
    related: list[str]


class PricingResponse(BaseModel):
    days: list[str]
    as_of: str | None
    extracted_days: int
    pending: int
    prices: list[PricingPrice]
    claims: list[PricingClaim]
    summary: dict[str, list[str]]


class PricingExtractResult(BaseModel):
    trade_date: str
    status: str
    observed: int | None = None
    new: int | None = None
    error: str | None = None
