"""RAG 질의응답 API — 검색된 수집 문서 근거 + 출처 인용 + 갭 분석."""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/spine/ask", tags=["spine"])


class AskRequest(BaseModel):
    question: str
    conversation_id: int | None = None   # 스레드 이어가기 (P2-2 UI 전까지는 미사용)


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
    answer: str | None
    citations: list[Citation]
    gaps: list[Gap]
    model: str | None   # epistemic: 답변은 이 모델의 '가설'
    conversation_id: int | None = None   # 적재된 스레드 (P2-0)
    as_of: str


@router.post("", response_model=AskResponse)
def ask_question(body: AskRequest):
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "질문이 비어 있습니다")
    # 스레드 이어가기: 이전 문답을 맥락으로 전달 (근거는 여전히 검색 문서만)
    history = None
    if body.conversation_id:
        from database import get_connection
        conn = get_connection()
        history = [dict(r) for r in conn.execute(
            "SELECT role, content FROM chat_messages WHERE conversation_id=? ORDER BY id DESC LIMIT 6",
            (body.conversation_id,))][::-1]
        conn.close()

    from pipeline.rag import ask
    try:
        result = ask(q, history=history)
    except Exception as e:
        raise HTTPException(502, f"응답 생성 실패: {e}")
    if result.get("error"):
        raise HTTPException(503, result["error"])

    # P2-0 대화 영속화 — 질문·답변 적재 (실패해도 응답은 정상)
    from pipeline.conversations import log_exchange_safe
    conv_id = log_exchange_safe(
        q, result.get("answer"),
        citations=result.get("citations"), gaps=result.get("gaps"),
        model=result.get("model"), channel="web",
        conversation_id=body.conversation_id)

    return AskResponse(
        answer=result.get("answer"),
        citations=result.get("citations", []),
        gaps=result.get("gaps", []),
        model=result.get("model"),
        conversation_id=conv_id,
        as_of=datetime.now(timezone.utc).isoformat(),
    )
