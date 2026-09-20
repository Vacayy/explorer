"""Validated public inputs for the isolated, read-only market analyst."""
from datetime import date
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class StrategyCondition(StrictModel):
    strategy_id: str = Field(min_length=1, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict, max_length=20)
    within_days: int = Field(default=1, ge=1, le=250, strict=True)

    @model_validator(mode="after")
    def supported(self):
        from pipeline.market_analysis.strategies import normalize_condition
        normalized = normalize_condition(self.model_dump())
        self.params = normalized["params"]
        return self


class AnalysisSpec(StrictModel):
    mode: Literal["pattern", "catalog"] = "pattern"
    strategy_conditions: list[StrategyCondition] = Field(default_factory=list, max_length=12)
    expression: dict[str, Any] | None = None
    universe_codes: list[str] | None = Field(default=None, max_length=10000)
    market: Literal["all", "KOSPI", "KOSDAQ"] = "all"
    as_of: date | None = None
    min_market_cap: float = Field(default=500_000_000_000, ge=0, le=1e17)
    pattern: Literal["inverse_head_shoulders", "none"] = "inverse_head_shoulders"
    lookback_days: int = Field(default=90, ge=1, le=500)
    window_scope: Literal["breakout", "formation"] = "breakout"
    pivot_width: int = Field(default=5, ge=1, le=30)
    shoulder_tolerance: float = Field(default=.15, ge=0, le=.5)
    require_52w: bool = True
    include_same_day: bool = False
    ma_period: int = Field(default=20, ge=2, le=250)
    hold_days: int = Field(default=14, ge=1, le=250)
    price_basis: Literal["close", "low"] = "close"
    require_ma: bool = True
    price_adjustment: Literal["unknown", "adjusted"] = "unknown"

    @model_validator(mode="before")
    @classmethod
    def catalog_defaults(cls, values):
        if isinstance(values, dict) and values.get("mode") == "catalog":
            values = {"min_market_cap": 0, "pattern": "none", "require_52w": False,
                      "require_ma": False, **values}
        return values

    @model_validator(mode="after")
    def consistent_conditions(self):
        if self.universe_codes is not None:
            if any(not re.fullmatch(r"[0-9A-Z]{6}", code) for code in self.universe_codes):
                raise ValueError("종목코드는 숫자·영문 대문자 6자리여야 합니다.")
            self.universe_codes = sorted(set(self.universe_codes))
        if self.expression is not None:
            from pipeline.market_analysis.expression import normalize_expression
            self.expression = normalize_expression(self.expression)
            if self.strategy_conditions:
                raise ValueError("조건식과 전략 목록은 동시에 지정할 수 없습니다.")
        ids = [condition.strategy_id for condition in self.strategy_conditions]
        if len(ids) != len(set(ids)):
            raise ValueError("같은 전략을 중복으로 선택할 수 없습니다.")
        if self.mode == "catalog":
            if not ids and self.expression is None:
                raise ValueError("전략을 하나 이상 선택해 주세요.")
            if self.pattern != "none" or self.require_52w or self.require_ma:
                raise ValueError("카탈로그 모드에서는 strategy_conditions 또는 expression으로 조건을 지정해 주세요.")
        return self


class RunRequest(StrictModel):
    question: str = Field(min_length=1, max_length=12000)
    request_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    as_of: date | None = None
    spec: AnalysisSpec | None = None
    parent_run_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    scope: Literal["universe", "candidates"] = "universe"
    date_policy: Literal["same", "latest"] = "same"
    spec_patch: dict[str, Any] | None = Field(default=None, max_length=24)

    @model_validator(mode="after")
    def nonblank(self):
        self.question = self.question.strip()
        if not self.question:
            raise ValueError("질문을 입력해 주세요.")
        if self.spec is not None:
            if self.as_of and self.spec.as_of and self.as_of != self.spec.as_of:
                raise ValueError("요청과 조건의 기준일이 다릅니다.")
        if self.parent_run_id:
            if self.spec is not None or self.as_of is not None:
                raise ValueError("후속 검색은 spec_patch와 date_policy로 변경해 주세요.")
        elif self.spec_patch is not None or self.scope != "universe" or self.date_policy != "same":
            raise ValueError("후속 검색 옵션에는 parent_run_id가 필요합니다.")
        if self.spec_patch is not None:
            forbidden = set(self.spec_patch) - set(AnalysisSpec.model_fields)
            if forbidden or {"as_of", "universe_codes", "price_adjustment"} & set(self.spec_patch):
                raise ValueError("후속 조건 변경에 허용하지 않는 필드가 있습니다.")
        return self


class ResumeRequest(StrictModel):
    interrupt_id: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)


ClarificationField = Literal["window_scope", "include_same_day", "price_basis"]


class ModelAction(StrictModel):
    action: Literal["interpret", "run_python", "ask_user", "finish"]
    plan: str = Field(default="", max_length=4000)
    spec: AnalysisSpec | None = None
    spec_patch: dict[str, Any] | None = Field(default=None, max_length=24)
    fields: list[ClarificationField] = Field(default_factory=list, max_length=3)
    unsupported_conditions: list[str] = Field(default_factory=list, max_length=20)
    code: str | None = Field(default=None, max_length=100_000)
    result_path: str | None = Field(default=None, max_length=180)
    evidence_ids: list[str] = Field(default_factory=list, max_length=60)
    summary: str = Field(default="", max_length=6000)

    @model_validator(mode="after")
    def required_action_fields(self):
        if self.action == "interpret" and ((self.spec is None) == (self.spec_patch is None)):
            raise ValueError("interpret requires exactly one of spec or spec_patch")
        if self.action == "run_python" and not self.code:
            raise ValueError("run_python requires code")
        if self.action == "ask_user" and not self.fields:
            raise ValueError("ask_user requires interpretation fields")
        if self.action == "finish" and (not self.result_path or not self.evidence_ids):
            raise ValueError("finish requires a result file and execution evidence")
        return self
