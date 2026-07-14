"""주제 내러티브 API — theme_surge 고도화 (pipeline/narrative). 2단 게으른 패턴."""
from fastapi import APIRouter
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/narrative", tags=["spine"])


class Narrative(BaseModel):
    status: str          # cached | fresh | empty | unavailable | failed | not_found
    title: str | None = None
    narrative: str | None = None
    created_at: str | None = None
    stale: bool = False


@router.get("", response_model=Narrative)
def get_narrative(topic: str):
    """캐시된 내러티브 + stale 플래그 — LLM 호출 없음."""
    from pipeline.narrative import cached_meta
    conn = get_connection()
    r = cached_meta(conn, topic)
    conn.close()
    return Narrative(**r)


@router.post("/compute", response_model=Narrative)
def compute(topic: str):
    """문서 집합이 바뀐 경우에만 opus 생성 — 멱등."""
    from pipeline.narrative import compute_narrative
    return Narrative(**compute_narrative(topic))
