"""Public contracts for the isolated Weekly experiment."""
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunRequest(StrictModel):
    request_key: str = Field(min_length=1, max_length=120)
    cutoff: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    mode: Literal["live", "public_reconstruction", "system_replay"] = "live"
    replay_run_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    scope: str = Field(default="미국 주식시장 Weekly. 중요한 질문을 직접 선정하고 산업·기업으로 연결한다.", max_length=4000)
    lookback_days: int = Field(default=730, ge=7, le=3650)
    model: str = Field(default="opus", min_length=1, max_length=100)
    reviewer_model: str = Field(default="opus", min_length=1, max_length=100)
    effort: Literal["low", "medium", "high"] = "high"
    max_steps: int = Field(default=24, ge=1, le=64)
    max_tool_calls: int = Field(default=40, ge=2, le=100)
    max_seconds: int = Field(default=1800, ge=90, le=7200)
    review_rounds: int = Field(default=2, ge=1, le=3)
    allow_network: bool = True

    @model_validator(mode="after")
    def replay_contract(self):
        if (self.mode == "system_replay") != bool(self.replay_run_id):
            raise ValueError("system_replay에는 이미 보존한 replay_run_id가 필요합니다")
        if self.cutoff > datetime.now(timezone.utc):
            raise ValueError("미래 cutoff로 실행할 수 없습니다")
        return self


class ResumeRequest(StrictModel):
    extra_steps: int = Field(default=8, ge=1, le=32)
    extra_seconds: int = Field(default=900, ge=90, le=3600)
    extra_tool_calls: int = Field(default=12, ge=1, le=40)


class Action(StrictModel):
    tool: str = Field(min_length=1, max_length=50)
    args: dict[str, Any] = Field(default_factory=dict)
    question: str = Field(min_length=1, max_length=1500)
    reason: str = Field(min_length=1, max_length=2000,
                        description="검증 가능한 조사 목적·선택 근거의 짧은 요약")


class Support(StrictModel):
    evidence_id: str
    quote: str = Field(default="", max_length=4000)


class Figure(StrictModel):
    id: str = Field(pattern=r"^n[0-9]+$")
    evidence_id: str
    path: str = Field(description="계산/시계열 JSON의 RFC6901 pointer, 예: /windows/0/return_pct")
    decimals: int = Field(default=2, ge=0, le=4)


class Claim(StrictModel):
    id: str = Field(pattern=r"^c[0-9]+$")
    kind: Literal["fact", "interpretation", "hypothesis"]
    text: str = Field(min_length=1, max_length=6000)
    supports: list[Support] = Field(default_factory=list, max_length=12)
    figures: list[Figure] = Field(default_factory=list, max_length=12)


class Section(StrictModel):
    heading: str = Field(min_length=1, max_length=180)
    claims: list[Claim] = Field(min_length=1, max_length=12)


class Hypothesis(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=1000)
    judgment: str = Field(min_length=1, max_length=2000)
    alternative: str = Field(min_length=1, max_length=2000)
    change_condition: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class Report(StrictModel):
    title: str = Field(min_length=1, max_length=180)
    standfirst: Claim
    sections: list[Section] = Field(min_length=1, max_length=10)
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=8)
    gaps: list[str] = Field(default_factory=list, max_length=20)

    def claims(self):
        return [self.standfirst, *(c for s in self.sections for c in s.claims)]


class ReviewIssue(StrictModel):
    claim_id: str
    severity: Literal["blocking", "warning"]
    code: str
    reason: str = Field(min_length=1, max_length=3000)


class ReviewResult(StrictModel):
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=50)
    assessment: str = Field(min_length=1, max_length=3000)


class RunView(BaseModel):
    id: str
    status: str
    created_at: str
    updated_at: str
    config: dict
    checkpoint: dict
    error: str | None = None
    cancel_requested: bool
    artifacts: list[str] = Field(default_factory=list)
