"""종목 묶음·감시 규칙 스키마 (docs/specs/portfolio-watch.md, D-185)."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GroupCreate(Strict):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["watch", "portfolio"] = "watch"
    note: str = Field(default="", max_length=2000)


class GroupUpdate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    kind: Literal["watch", "portfolio"] | None = None
    note: str | None = Field(default=None, max_length=2000)


class MemberCreate(Strict):
    """수량·매수가는 받지 않는다 — 포트폴리오 보유는 거래 원장(portfolio_transactions, D-212)만 기록한다."""
    stock_code: str = Field(pattern=r"^[0-9A-Z]{6}$")
    conviction: int | None = Field(default=None, ge=1, le=5)
    target_price: int | None = Field(default=None, ge=0)
    thesis: str | None = Field(default=None, max_length=4000)


class MemberUpdate(Strict):
    conviction: int | None = Field(default=None, ge=1, le=5)
    target_price: int | None = Field(default=None, ge=0)
    thesis: str | None = Field(default=None, max_length=4000)


class RuleInput(Strict):
    strategy_id: str = Field(min_length=1, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)
    within_days: int = Field(default=1, ge=1, le=250)
    source_strategy_id: str | None = Field(default=None, max_length=64)
    source_version: int | None = Field(default=None, ge=1)


class RulesPut(Strict):
    default: list[RuleInput] = Field(default_factory=list, max_length=24)
    members: dict[str, list[RuleInput]] = Field(default_factory=dict)


class ReasonCreate(BaseModel):
    """관심 종목 이유 감시 시작(D-227) — 왜 보고 있나 / 무엇이 오면 움직이나."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    stock_code: str = Field(pattern=r"^[0-9A-Z]{6}$")
    why: str = Field(min_length=5, max_length=4000)             # 멤버 메모(thesis) 한도와 같게
    trigger: str = Field(default="", max_length=1000)
