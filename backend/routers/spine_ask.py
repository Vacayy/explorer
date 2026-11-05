"""대화 질의응답 API — 라우터·도구·종합(pipeline/chat.py, D-131) + 출처 인용 + 갭 분석.

P2-2 후속 — 비동기화: 질문을 즉시 적재하고 conversation_id를 바로 반환,
답변은 백그라운드에서 생성해 스레드에 append. 진행 중 상태가 서버 상태이므로
탭 이동·새로고침에도 유실되지 않는다 (FE는 '마지막 메시지=user'를 생성 중으로 폴링).
DB가 진실원천, 진행 표시·본문 스트리밍은 `GET /conversations/{id}/stream`(SSE)이 가속기(D-130).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from models.chat_targets import AttachmentRef

router = APIRouter(prefix="/api/spine/ask", tags=["spine"])


class Quote(BaseModel):
    """드래그 인용 (D-146) — 선택 문장만으로는 맥락을 모른다. 문단·출처·근거를 함께 받는다."""
    message_id: int | None = None                 # 인용된 assistant 메시지 (전문을 한 번만 싣기 위한 키)
    selected: str                                  # 사용자가 지목한 문장
    block: str | None = None                       # 그 문장이 속한 문단 전체
    citations: list[dict] | None = None            # 그 대목이 딛던 근거 [{kind,title,doc_id}]
    doc_id: int | None = None                      # 문서에서 지목했으면 그 문서 (message_id 없음, canvas.md §2)
    doc_title: str | None = Field(default=None, max_length=300)


class PageContext(BaseModel):
    """AI 대화 패널이 보는 화면 (docs/specs/app-shell.md §5) — 지시어 해석용, 메시지 본문에는 저장하지 않는다."""
    kind: str = Field(default="page", max_length=20)
    label: str = Field(max_length=200)
    path: str = Field(default="", max_length=500)
    ref: str | None = Field(default=None, max_length=100)


class AskRequest(BaseModel):
    question: str
    conversation_id: int | None = None   # 스레드 이어가기
    quote: Quote | None = None
    page_context: PageContext | None = None
    document_ids: list[int] | None = Field(default=None, max_length=12)
    # 지금 붙어 있는 대상 전체(클라이언트가 ×로 뺀 것은 빠진 채로 온다). None이면 이 대화의 기존 목록을 그대로 둔다.
    attachments: list[AttachmentRef] | None = Field(default=None, max_length=12)


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


def _generate_answer(conversation_id: int, question: str, quote: dict | None = None, *, page_context: dict | None = None):
    """백그라운드: 웹·봇 공용 경로 (pipeline/chat.py) — 어떤 경로로도 assistant 메시지로 닫힌다."""
    from pipeline.chat import generate_answer
    generate_answer(conversation_id, question, quote, page_context=page_context)


def _attachment_refs(body: AskRequest) -> list[dict] | None:
    """요청의 붙인 대상 → 저장할 전체 목록. 변화가 없으면 None(기존 목록 유지).

    `attachments`는 지금 붙어 있는 전체 목록이다. 예전 경로의 `document_ids`는 자료 대상으로 바꿔 같은 목록에 합친다.
    새로 붙인 대상이 너무 많거나 찾을 수 없으면 422 — 조용히 빼지 않는다.
    한 번에 5개 제한은 `attachments`에만 건다(예전 `document_ids`는 12개까지 그대로)."""
    if body.attachments is None and body.document_ids is None:
        return None
    from database import get_connection
    from pipeline import chat_targets as ct
    from pipeline.chat_memory import conversation_state
    state = conversation_state(body.conversation_id)
    previous = [r for r in state.get("attached_refs") or [] if isinstance(r, dict)]
    old_docs = state.get("attached_doc_ids") or []
    previous += [{"kind": "doc", "ref": str(d), "label": ""} for d in old_docs if not any(r.get("kind") == "doc" and r.get("ref") == str(d) for r in previous)]
    if body.attachments is not None:
        incoming = [a.model_dump() for a in body.attachments]
    else:   # 예전 경로: 자료 목록만 바꾸고 다른 대상은 그대로
        incoming = [r for r in previous if r.get("kind") != "doc"]
    conn = get_connection()
    try:
        for doc_id in body.document_ids or []:
            row = conn.execute("SELECT title FROM raw_documents WHERE id=?", (doc_id,)).fetchone()
            incoming.append({"kind": "doc", "ref": str(doc_id), "label": (row["title"] if row else None) or f"자료 #{doc_id}"})
        try:
            refs, new = ct.merge_refs(previous, incoming, max_new=ct.MAX_NEW_PER_MESSAGE if body.attachments is not None else ct.MAX_ATTACHED)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        for r in new:
            if not ct.resolve(conn, r)["available"]:
                raise HTTPException(422, f"붙일 대상을 찾을 수 없습니다: {ct.KIND_LABEL[r['kind']]} {r['label'] or r['ref']}")
    finally:
        conn.close()
    return refs


@router.post("", response_model=AskResponse)
def ask_question(body: AskRequest, background: BackgroundTasks):
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "질문이 비어 있습니다")

    if body.document_ids:
        from pipeline.expectation_evidence import get_document
        if any(doc_id < 1 or get_document(doc_id) is None for doc_id in body.document_ids):
            raise HTTPException(422, "첨부할 수집 자료를 찾을 수 없습니다")
    refs = _attachment_refs(body)
    from pipeline.conversations import log_question
    conv_id = log_question(q, channel="web", conversation_id=body.conversation_id, attachments=refs or None)
    if refs is not None:
        # Persist before generation: navigation/reload/follow-up keeps the selected targets and corpus.
        from pipeline.chat_memory import set_attached_refs
        set_attached_refs(conv_id, refs)
    background.add_task(_generate_answer, conv_id, q, body.quote.model_dump() if body.quote else None,
                        page_context=body.page_context.model_dump() if body.page_context else None)

    return AskResponse(
        answer=None, citations=[], gaps=[], model=None,
        conversation_id=conv_id, status="pending",
        as_of=datetime.now(timezone.utc).isoformat(),
    )
