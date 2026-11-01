"""관측 API (docs/specs/observability.md, D-283) — 사용 이벤트 수신 · 관리자 '관측' 탭 요약."""
from fastapi import APIRouter

from models.observe import ObserveSummary, UsageBatch

router = APIRouter(tags=["spine"])


@router.post("/api/spine/usage", status_code=204)
def usage(body: UsageBatch):
    """화면이 묶어 보내는 사용 이벤트(view·leave·action·open). 로컬에만 쌓는다."""
    from pipeline.observe import save_events
    save_events([e.model_dump() for e in body.events])


@router.get("/api/spine/admin/observe", response_model=ObserveSummary)
def observe(days: int = 7):
    """잘 도는가·얼마나 드는가·무엇을 쓰는가·도움이 되는가 — 관리자 '관측' 탭. LLM 0."""
    from pipeline.observe import summary
    return summary(max(1, min(days, 90)))
