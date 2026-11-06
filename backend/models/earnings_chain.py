"""콜 상세 체인 응답 — GET /api/spine/transcript/chain/{id} (pipeline.earnings_chain.chain_detail).

모양의 원본은 파이프라인 dict다. 키를 바꾸면 이 모델도 같은 커밋에서 바꾼다(api-contract).
"""
from typing import Literal

from pydantic import BaseModel

EvalVerdict = Literal["hit", "underweighted", "noise", "missed", "minor"]


class PtWindow(BaseModel):
    n: int
    up: int
    down: int
    median_pct: float | None
    examples: list[str]


class ExpectationQuant(BaseModel):
    etf: str | None = None
    eps_est: float | None = None
    rev_est: float | None = None
    eps_rev_up30: int | None = None
    eps_rev_down30: int | None = None
    runup30: float | None = None
    runup30_vs_spy: float | None = None
    runup30_vs_etf: float | None = None
    pt30: PtWindow | None = None
    implied_move: float | None = None


class ExpectationIssue(BaseModel):
    issue: str
    why: str | None = None
    good: str | None = None
    bad: str | None = None
    weight: Literal["high", "mid", "low"] | None = None
    cites: list[int] | None = None


class Expectation(BaseModel):
    ticker: str
    fiscal_year: int
    fiscal_period: str
    snapshot: Literal["d7", "d1"]
    event_date: str | None
    quant: ExpectationQuant | None
    issues: list[ExpectationIssue] | None
    points: list[str] | None
    positioning: str | None
    thin: str | None
    n_docs: int | None
    prompt_version: str | None
    created_at: str


class Surprise(BaseModel):
    revenue: str | None = None
    eps: str | None = None
    guidance: str | None = None
    one_off: str | None = None


class IssueVerdict(BaseModel):
    issue: str
    drove: str
    outcome: str | None = None


class ReactionGrade(BaseModel):
    issue: str
    weight: Literal["high", "mid", "low"] | None
    drove: Literal["major", "minor", "none"] | None
    outcome: str | None
    verdict: EvalVerdict | None


class ReactionMeta(BaseModel):
    headline: str | None = None
    interpretation: Literal["positive", "neutral", "negative"] | None = None
    welcomed: list[str] | None = None
    questioned: list[str] | None = None
    surprise: Surprise | None = None
    call_points: list[str] | None = None
    react_points: list[str] | None = None
    issue_verdicts: list[IssueVerdict] | None = None
    missed: list[str] | None = None
    vs_prev: list[str] | None = None
    d1: float | None = None
    d7: float | None = None
    grades: list[ReactionGrade] | None = None
    expectation_prompt: str | None = None


class ChainPoint(BaseModel):
    date: str
    offset: int
    ret: float
    bench: float
    excess: float
    volume: float | None


class MentionDay(BaseModel):
    day: str   # 'MM-DD' 한국 시각
    n: int


class ChainHistoryRow(BaseModel):
    fiscal: str
    event_date: str
    season: str
    transcript_id: int | None
    d1: float | None
    d7: float | None
    d30: float | None
    # 분기 수익률 — 발표 전 종가 → 다음 발표 전 거래일 종가, 업종 ETF 대비 %p. 다음 발표 전이면 마지막 종가까지(dq_partial)
    dq: float | None
    dq_partial: bool | None
    dq_end: str | None
    follow: Literal["유지", "확대", "되돌림", "반전"] | None
    pt_up: int | None
    pt_down: int | None
    headline: str | None
    reaction: Literal["interim", "final"] | None


class ChainDetail(BaseModel):
    ticker: str
    name: str | None
    sector: str
    sector_name: str
    etf: str
    event_date: str | None
    expectation: Expectation | None
    reaction_meta: ReactionMeta | None
    reaction_status: Literal["interim", "final"] | None
    series: list[ChainPoint]
    mentions: list[MentionDay]
    pt_after: PtWindow | None
    history: list[ChainHistoryRow]
