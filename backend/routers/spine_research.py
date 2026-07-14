"""리서치 후보 API — 값싼 제안 목록 + 승인(opus 리서치)/기각 (pipeline/research_candidates)."""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/spine/research", tags=["spine"])


class RevisionCall(BaseModel):
    direction: str
    rationale: str | None = None


class Candidate(BaseModel):
    id: int
    stock_code: str
    name: str | None = None
    detected_date: str
    rs_short: int | None = None
    rs_short_prev: int | None = None
    market_cap: int | None = None
    sector: str | None = None
    share_delta_pp: float | None = None
    status: str
    revision_call: RevisionCall | None = None
    researched_at: str | None = None


class CandidateList(BaseModel):
    items: list[Candidate]


class ApproveResult(BaseModel):
    status: str                       # done | not_found
    stock_code: str | None = None
    brief_status: str | None = None
    revision_call: RevisionCall | None = None
    brief: str | None = None


@router.get("/candidates", response_model=CandidateList)
def candidates(status: str = "proposed"):
    """리서치 제안 목록 — LLM 0 (값싼 감지 결과)."""
    from pipeline.research_candidates import list_candidates
    return CandidateList(items=list_candidates(status))


@router.post("/candidates/{candidate_id}/approve", response_model=ApproveResult)
def approve(candidate_id: int):
    """승인 → stock_brief(opus) 실행, 추정치 방향 콜 기록."""
    from pipeline.research_candidates import approve_candidate
    return ApproveResult(**approve_candidate(candidate_id))


@router.post("/candidates/{candidate_id}/dismiss")
def dismiss(candidate_id: int):
    from pipeline.research_candidates import dismiss_candidate
    return dismiss_candidate(candidate_id)
