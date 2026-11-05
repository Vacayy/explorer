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
    ref: float | None = None            # 이평선 조건의 현재 이평선 값(국내 원 단위 정수, 미국 달러 소수 2자리)
    newly_met: bool = False             # 오늘 새로 충족(확인 항목은 오늘 확인) — 홈 › 내 종목 알림 줄


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
    market: Literal["kr", "us"] = "kr"  # us = 미국 일봉(us_prices) 기준, 수급·공시 없음
    price: float | None = None
    change_pct: float | None = None
    as_of: str | None = None
    source: str | None = None           # live(장중 실시간, 국내만) | close(종가)
    last_close_date: str | None = None
    chart: dict
    technicals: dict
    flows: dict | None = None           # 수집 전이거나 미국 종목이면 None
    issues: dict
    conditions: list[TrackerCondition]


class TrackerStatusCondition(BaseModel):
    id: int
    role: Literal["entry", "exit", "check"]
    label: str
    status: Literal["met", "not_met", "pending", "unknown"] = "unknown"
    newly_met: bool = False


class TrackerStatusItem(BaseModel):
    code: str
    name: str
    market: Literal["kr", "us"] = "kr"
    as_of: str | None = None
    met: int = 0                        # 지금 충족한 조건 수
    newly_met: int = 0                  # 오늘 새로 충족한 조건 수
    conditions: list[TrackerStatusCondition]


class TrackerStatus(BaseModel):
    """추적 종목 전체의 조건 충족 요약 — 홈 › 내 종목 머리 줄 '충족 n'·알림 줄. 저장된 시세·조건만 읽는다(차트·신호·수급·이슈 없음)."""
    items: list[TrackerStatusItem]
    met: int = 0
    newly_met: int = 0
