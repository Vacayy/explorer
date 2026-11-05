"""AI 대화 › 대상 붙이기 후보 (ia-redesign §4.14a, D-311) — `@`·'＋' 팝오버가 부른다. 모델 호출 없음."""
from fastapi import APIRouter, Query

from database import get_connection
from models.chat_targets import ChatTargetSearch, TargetKind

router = APIRouter(prefix="/api/spine/chat/targets", tags=["spine"])


@router.get("", response_model=ChatTargetSearch)
def targets(q: str = Query("", max_length=80), kind: TargetKind | None = None):
    """종류별 후보. kind가 없으면 종류마다 4개, 있으면 그 종류만 20개. 빈 q는 서사·질문·자료·리포트·Peer 그룹의 최근 것."""
    from pipeline.chat_targets import search
    conn = get_connection()
    try:
        return ChatTargetSearch(query=q.strip(), kind=kind, groups=search(conn, q, kind))
    finally:
        conn.close()
