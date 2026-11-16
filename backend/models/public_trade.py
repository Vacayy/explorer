"""Stored customs observations for the fixed public catalog, never personal follows."""
from typing import Literal
from pydantic import BaseModel


class PublicTradePoint(BaseModel):
    period: str
    value: float | None
    export_usd: float | None = None
    import_usd: float | None = None
    balance_usd: float | None = None
    ma12: float | None = None
    mom: float | None = None
    yoy: float | None = None
    qoq: float | None = None
    yoy3m: float | None = None


class PublicTradeMetrics(PublicTradePoint):
    z: float | None = None
    flag: Literal['none','new','surge','plunge']
    reason: str
    delta_usd: float | None = None
    contribution: float | None = None


class PublicTradeRow(BaseModel):
    hs_code: str
    item_name: str
    group_label: str
    nested_in: str | None
    fetched_at: str | None
    missing: bool
    metrics: PublicTradeMetrics
    series: list[PublicTradePoint]


class PublicTradeAggregate(BaseModel):
    value: float | None
    observed_count: int
    total_count: int
    partial: bool


class PublicTradeGroup(PublicTradeAggregate):
    group_label: str


class PublicTradeResponse(BaseModel):
    flow: Literal['export','import']
    period: str | None
    latest_period: str | None
    periods: list[str]
    months: Literal[24,60]
    unit: Literal['USD'] = 'USD'
    valuation: Literal['FOB','CIF']
    source: str
    source_url: str
    note: str
    fetched_at: str | None
    empty: bool
    partial: bool
    rows: list[PublicTradeRow]
    total: PublicTradeAggregate
    groups: list[PublicTradeGroup]
