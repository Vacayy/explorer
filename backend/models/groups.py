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
    stock_code: str = Field(pattern=r"^[0-9A-Z]{6}$")
    quantity: float | None = Field(default=None, ge=0)
    avg_price: float | None = Field(default=None, ge=0)
    bought_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    conviction: int | None = Field(default=None, ge=1, le=5)
    target_price: int | None = Field(default=None, ge=0)
    thesis: str | None = Field(default=None, max_length=4000)


class MemberUpdate(Strict):
    quantity: float | None = Field(default=None, ge=0)
    avg_price: float | None = Field(default=None, ge=0)
    bought_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
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
