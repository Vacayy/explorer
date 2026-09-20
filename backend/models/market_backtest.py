"""Bounded inputs for deterministic, read-only strategy comparisons."""
from datetime import date
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .market_analysis import StrictModel


class BacktestSpec(StrictModel):
    start_date: str = "2026-02-03"
    split_date: str = "2026-07-01"
    end_date: str = "2026-09-18"
    initial_cash: float = Field(default=100_000_000, ge=100_000, le=100_000_000_000)
    max_positions: int = Field(default=20, ge=1, le=100)
    rebalance_every: int = Field(default=20, ge=5, le=60)
    buy_cost_bps: float = Field(default=25, ge=0, le=1000)
    sell_cost_bps: float = Field(default=25, ge=0, le=1000)
    min_market_cap: float = Field(default=0, ge=0, le=1e15)
    markets: list[Literal["KOSPI", "KOSDAQ", "KONEX", "UNKNOWN"]] = Field(
        default_factory=lambda: ["KOSPI", "KOSDAQ"], min_length=1, max_length=4)

    @field_validator("start_date", "split_date", "end_date")
    @classmethod
    def iso_date(cls, value):
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.")
        return value

    @field_validator("initial_cash", "max_positions", "rebalance_every", "buy_cost_bps",
                     "sell_cost_bps", "min_market_cap", mode="before")
    @classmethod
    def numeric(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("숫자로 입력해야 합니다.")
        return value

    @field_validator("markets")
    @classmethod
    def unique_markets(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("시장을 중복 지정할 수 없습니다.")
        return value

    @model_validator(mode="after")
    def dates(self):
        start, split, end = map(date.fromisoformat, (self.start_date, self.split_date, self.end_date))
        if not start < split <= end:
            raise ValueError("시작일 < 평가 시작일 ≤ 종료일이어야 합니다.")
        if (end - start).days > 730:
            raise ValueError("한 번의 비교 기간은 최대 730일입니다.")
        return self


class BacktestRequest(StrictModel):
    spec: BacktestSpec = Field(default_factory=BacktestSpec)
    request_key: str | None = Field(default=None, min_length=8, max_length=128)
