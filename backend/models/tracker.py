"""종목 추적 위젯 스키마 (docs/specs/stock-tracker.md)."""
from typing import Literal

from pydantic import BaseModel


class TrackerCondition(BaseModel):
    id: int
    stock_code: str
    role: Literal["entry", "exit", "check"]
    kind: Literal["price_below", "price_above", "close_below_ma", "close_above_ma", "manual"]
    level: float | None = None
    ma: int | None = None
    label: str
    note: str | None = None
    done: int = 0
    status: Literal["met", "not_met", "pending", "unknown"] = "unknown"
    distance_pct: float | None = None   # 가격·이평선 대비 현재가 거리(%)
    ref: int | None = None              # 이평선 조건의 현재 이평선 값


class TrackerConditionIn(BaseModel):
    role: Literal["entry", "exit", "check"]
    kind: Literal["price_below", "price_above", "close_below_ma", "close_above_ma", "manual"]
    level: float | None = None
    ma: int | None = None
    label: str
    note: str | None = None


class TrackerConditionPatch(BaseModel):
    done: int | None = None
    label: str | None = None
    level: float | None = None
    note: str | None = None


class TrackerView(BaseModel):
    code: str
    name: str
    price: float | None = None
    change_pct: float | None = None
    as_of: str | None = None
    source: str | None = None           # live(장중 실시간) | close(종가)
    last_close_date: str | None = None
    chart: dict
    technicals: dict
    flows: dict | None = None           # 수집 전이면 None
    issues: dict
    conditions: list[TrackerCondition]
