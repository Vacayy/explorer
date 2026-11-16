"""Private fixture router for exercising the existing chat API contract."""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pipeline.postgres_conversations import ConversationNotFound
from pipeline.postgres_chat_generation import generate_answer
from routers.spine_ask import AskRequest, AskResponse
from routers.spine_conversations import ChatMessage, ConversationDetail, ConversationItem


def create_router(store, tools, *, owner_chat_id=None):
    router = APIRouter()

    @router.post('/api/spine/ask', response_model=AskResponse)
    def ask(body: AskRequest, background: BackgroundTasks):
        question = body.question.strip()
        if not question:
            raise HTTPException(400, '질문이 비어 있습니다')
        if body.document_ids or body.attachments:
            raise HTTPException(422, '격리 시험에서는 새 첨부를 지원하지 않습니다')
        try:
            cid, _ = store.create_question(question, conversation_id=body.conversation_id,
                                           owner_chat_id=owner_chat_id)
        except ConversationNotFound as exc:
            raise HTTPException(404, '대화를 찾을 수 없습니다') from exc
        background.add_task(generate_answer, store, tools, cid, question, owner_chat_id=owner_chat_id,
                            quote=body.quote.model_dump() if body.quote else None,
                            page_context=body.page_context.model_dump() if body.page_context else None)
        return AskResponse(answer=None, citations=[], gaps=[], model=None, conversation_id=cid,
                           status='pending', as_of=datetime.now(timezone.utc).isoformat())

    @router.get('/api/spine/conversations', response_model=list[ConversationItem])
    def list_conversations(limit: int = 20, stock: str | None = None):
        if stock:
            raise HTTPException(422, '격리 시험에서는 종목별 대화 목록을 지원하지 않습니다')
        return store.list(owner_chat_id=owner_chat_id, limit=limit)

    @router.get('/api/spine/conversations/{conversation_id}', response_model=ConversationDetail)
    def detail(conversation_id: int):
        try:
            conversation, messages = store.detail(conversation_id, owner_chat_id=owner_chat_id)
        except ConversationNotFound as exc:
            raise HTTPException(404, '대화를 찾을 수 없습니다') from exc
        state = json.loads(conversation['state_json'] or '{}')
        if state.get('attached_refs') or state.get('attached_doc_ids'):
            raise HTTPException(422, '격리 시험에서는 첨부된 대화 조회를 지원하지 않습니다')
        return ConversationDetail(id=conversation['id'], title=conversation['title'],
                                  channel=conversation['channel'], messages=[
            ChatMessage(id=m['id'], role=m['role'], content=m['content'], model=m['model'],
                        citations=json.loads(m['citations_json']) if m['citations_json'] else None,
                        gaps=json.loads(m['gaps_json']) if m['gaps_json'] else None,
                        route=json.loads(m['route_json']) if m['route_json'] else None,
                        attachments=json.loads(m['attachments_json']) if m['attachments_json'] else None,
                        created_at=m['created_at']) for m in messages])
    return router
