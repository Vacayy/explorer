"""Bounded research decisions; evidence, source opinion and house view stay separate."""
from typing import Literal

from pydantic import Field, model_validator

from .weekly_reader import Judgment, Strict


class QuestionBrief(Strict):
    id: str = Field(pattern=r"^q[1-4]$")
    question: str
    why_now: str
    competing_explanations: list[str] = Field(min_length=2, max_length=4)
    decision_at_stake: str
    evidence_needed: list[str] = Field(min_length=1, max_length=5)
    search_terms: list[str] = Field(min_length=2, max_length=5)
    completion_condition: str


class ResearchAgenda(Strict):
    market_puzzle: str
    questions: list[QuestionBrief] = Field(min_length=2, max_length=4)
    deferred: list[str] = Field(max_length=6)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("Duplicate question id")
        return self


class SearchRequest(Strict):
    query: str = Field(min_length=1, max_length=160)
    channel: str = ""
    person: str = ""
    since: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    until: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    offset: int = Field(default=0, ge=0, le=120)


class ReadRequest(Strict):
    source_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    start: int = Field(default=0, ge=0)
    length: int = Field(default=12000, ge=200, le=18000)


class Citation(Strict):
    source_id: str
    quote: str = Field(min_length=8)


class ClaimCitationRepair(Strict):
    claim_id: str
    citations: list[Citation] = Field(min_length=1, max_length=4)


class CitationRepairs(Strict):
    repairs: list[ClaimCitationRepair] = Field(min_length=1, max_length=7)


class ResearchClaim(Strict):
    id: str = Field(pattern=r"^q[1-4]-c[0-9]+$")
    statement: str
    kind: Literal["observation", "source_view", "inference"]
    citations: list[Citation] = Field(min_length=1, max_length=4)
    limitation: str


class ResearchMemo(Strict):
    question_id: str
    answer: str
    expectations_event_reaction: str
    claims: list[ResearchClaim] = Field(min_length=2, max_length=7)
    strongest_alternative: str
    pricing_interpretation: str
    response_implication: str
    change_condition: str
    unresolved: list[str] = Field(max_length=5)


class ResearchStep(Strict):
    decision_reason: str
    searches: list[SearchRequest] = Field(default_factory=list, max_length=3)
    reads: list[ReadRequest] = Field(default_factory=list, max_length=6)
    memo: ResearchMemo | None = None

    @model_validator(mode="after")
    def action_or_finish(self):
        if self.memo is not None and (self.searches or self.reads):
            raise ValueError("Read results before finishing a memo")
        if self.memo is None and not (self.searches or self.reads):
            raise ValueError("Choose a tool or submit a memo")
        return self


class ResearchRequest(Strict):
    question_id: str
    problem: str
    route: Literal["source", "interpretation", "wording"]
    query: str
    evidence_needed: str
    completion_condition: str
    decision_impact: str


class ChallengeSet(Strict):
    assessment: str
    requests: list[ResearchRequest] = Field(max_length=3)


class ClaimDisposition(Strict):
    claim_id: str
    status: Literal["adopted", "rejected", "unconfirmed"]
    reason: str


class DecisionBrief(Strict):
    judgment: Judgment
    dispositions: list[ClaimDisposition] = Field(min_length=1)
    writing_source_ids: list[str] = Field(min_length=1, max_length=28)
    unresolved_material: list[str]


class DecisionSelectionRepair(Strict):
    disposition_updates: list[ClaimDisposition]
    writing_source_ids: list[str] = Field(min_length=1, max_length=28)
    judgment: Judgment | None = None
    additional_material_gaps: list[str] = Field(default_factory=list, max_length=5)
