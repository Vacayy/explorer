"""대화 질의응답 API — 라우터·도구·종합(pipeline/chat.py, D-131) + 출처 인용 + 갭 분석.

P2-2 후속 — 비동기화: 질문을 즉시 적재하고 conversation_id를 바로 반환,
답변은 백그라운드에서 생성해 스레드에 append. 진행 중 상태가 서버 상태이므로
탭 이동·새로고침에도 유실되지 않는다 (FE는 '마지막 메시지=user'를 생성 중으로 폴링).
DB가 진실원천, 진행 표시·본문 스트리밍은 `GET /conversations/{id}/stream`(SSE)이 가속기(D-130).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/spine/ask", tags=["spine"])


class AskRequest(BaseModel):
    question: str
    conversation_id: int | None = None   # 스레드 이어가기


class Citation(BaseModel):
    n: int
    kind: str = "doc"             # doc | narrative | edges | knowledge | question | lens | quote | regime | briefing …
    doc_id: int | None = None
    title: str
    href: str | None = None       # 내부 경로 (문서 /doc/:id, 내러티브 /narrative?topic= …)
    published_at: str | None = None


class Gap(BaseModel):
    type: str    # unsupported | contradiction | stale | missing
    note: str


class AskResponse(BaseModel):
    answer: str | None            # 비동기 — 항상 None (스레드 폴링으로 수신)
    citations: list[Citation]
    gaps: list[Gap]
    model: str | None
    conversation_id: int | None = None
    status: str = "pending"       # pending — 백그라운드 생성 중
    as_of: str


def _generate_answer(conversation_id: int, question: str):
    """백그라운드: 웹·봇 공용 경로 (pipeline/chat.py) — 어떤 경로로도 assistant 메시지로 닫힌다."""
    from pipeline.chat import generate_answer
    generate_answer(conversation_id, question)


@router.post("", response_model=AskResponse)
def ask_question(body: AskRequest, background: BackgroundTasks):
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "질문이 비어 있습니다")

    from pipeline.conversations import log_question
    conv_id = log_question(q, channel="web", conversation_id=body.conversation_id)
    background.add_task(_generate_answer, conv_id, q)

    return AskResponse(
        answer=None, citations=[], gaps=[], model=None,
        conversation_id=conv_id, status="pending",
        as_of=datetime.now(timezone.utc).isoformat(),
    )
