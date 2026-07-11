"""RAG 질의응답 API — 검색된 수집 문서 근거 + 출처 인용 + 갭 분석.

P2-2 후속 — 비동기화: 질문을 즉시 적재하고 conversation_id를 바로 반환,
답변은 백그라운드에서 생성해 스레드에 append. 진행 중 상태가 서버 상태이므로
탭 이동·새로고침에도 유실되지 않는다 (FE는 '마지막 메시지=user'를 생성 중으로 폴링).
웹소켓·큐 불필요 — 1인 사용 스케일에서 DB + 폴링이 가장 단순한 정답.
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
    doc_id: int
    title: str
    url: str
    source_type: str
    published_at: str


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
    """백그라운드: RAG 실행 → 답변 append. 실패해도 스레드가 영원히 '생성 중'으로
    남지 않도록 실패 메시지를 append한다."""
    from pipeline.conversations import append_assistant
    from database import get_connection

    # 이 질문 이전의 문답만 맥락으로 (방금 적재된 user 메시지 제외)
    conn = get_connection()
    history = [dict(r) for r in conn.execute("""
        SELECT role, content FROM chat_messages
        WHERE conversation_id=? ORDER BY id DESC LIMIT 7""", (conversation_id,))][::-1]
    conn.close()
    if history and history[-1]["role"] == "user" and history[-1]["content"] == question:
        history = history[:-1]

    from pipeline.rag import ask
    try:
        result = ask(question, history=history or None)
    except Exception as e:
        append_assistant(conversation_id, f"답변 생성에 실패했습니다: {str(e)[:150]} — 다시 질문해주세요.")
        return
    if result.get("error"):
        append_assistant(conversation_id, f"답변 생성 불가: {result['error']}")
        return
    append_assistant(
        conversation_id,
        result.get("answer") or "관련 수집 문서가 없어 답할 수 없습니다.",
        citations=result.get("citations"), gaps=result.get("gaps"),
        model=result.get("model"))


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
