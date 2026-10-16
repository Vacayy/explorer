"""Reader-facing Weekly contract. V1 research reports remain readable unchanged."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceLink(Strict):
    source_id: str
    anchor: str = Field(min_length=1, description="Exact phrase in the paragraph that this citation supports")
    quote: str = Field(min_length=8, description="Exact passage in the supplied source; never an invented quote")


class Paragraph(Strict):
    id: str = Field(pattern=r"^p[0-9]+$")
    text: str = Field(min_length=1, max_length=3500)
    sources: list[SourceLink] = Field(default_factory=list, max_length=8)
    charts: list[str] = Field(default_factory=list, max_length=2)


class ReaderSection(Strict):
    heading: str = Field(min_length=1, max_length=150)
    paragraphs: list[Paragraph] = Field(min_length=1, max_length=6)


class ReaderBrief(Strict):
    schema_version: Literal[2] = 2
    title: str = Field(min_length=1, max_length=150)
    opening: Paragraph
    sections: list[ReaderSection] = Field(min_length=2, max_length=7)

    def paragraphs(self):
        return [self.opening, *(p for s in self.sections for p in s.paragraphs)]


class ParagraphCitations(Strict):
    paragraph_id: str
    sources: list[SourceLink] = Field(max_length=8)


class ReaderCitationRepairs(Strict):
    paragraphs: list[ParagraphCitations]
    unresolved: list[str] = Field(default_factory=list)


class TurningCondition(Strict):
    event_or_question: str
    observation: str
    why_it_matters: str
    response: str
    evidence_ids: list[str]


class Judgment(Strict):
    week_in_review: str
    market_state: str
    central_question: str
    preferred_explanation: str
    decisive_evidence: list[str] = Field(min_length=1, max_length=8)
    strongest_counterargument: str
    current_response: str
    opportunity_cost: str
    change_conditions: list[TurningCondition] = Field(min_length=1, max_length=4)
    critical_gaps: list[str] = Field(default_factory=list)


class ReaderIssue(Strict):
    severity: Literal["blocking", "warning"]
    location: str
    reason: str
    requested_change: str


class FactualReview(Strict):
    assessment: str
    issues: list[ReaderIssue]


class InvestorReview(Strict):
    market_state_understood: str
    author_view_understood: str
    current_response_understood: str
    change_conditions_understood: str
    verdict: Literal["readable", "rewrite"]
    issues: list[ReaderIssue]


class ComparisonRequest(Strict):
    request_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    source_run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    workflow: Literal["comparison", "briefing", "research"] = "comparison"
    week_start: date
    week_end: date
    outlook_start: date
    outlook_end: date
    model: str = "opus"
    effort: Literal["low", "medium", "high"] = "high"
    completion_engine: Literal["default", "codex-exec"] = "default"
    completion_model: str | None = None
    call_timeout: int = Field(default=360, ge=30, le=600)
    max_seconds: int = Field(default=2100, ge=90, le=7200)

    @model_validator(mode="after")
    def periods(self):
        if self.completion_engine == "codex-exec" and not self.completion_model:
            raise ValueError("Codex completion 모델을 명시하세요")
        if not self.week_start <= self.week_end < self.outlook_start <= self.outlook_end:
            raise ValueError("회고 주간과 다음 대응 주간을 순서대로 지정하세요")
        if self.max_seconds < self.call_timeout + 5:
            raise ValueError("전체 시간 예산은 호출 상한과 정리 시간(5초)보다 커야 합니다")
        return self
