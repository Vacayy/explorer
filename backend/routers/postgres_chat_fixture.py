"""Private fixture router for exercising the existing chat API contract."""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from starlette.concurrency import run_in_threadpool
from pipeline.postgres_conversations import ConversationNotFound, DocumentNotFound
from pipeline.postgres_chat_generation import generate_answer
from routers.spine_ask import AskRequest, AskResponse
from routers.spine_conversations import ChatMessage, ConversationDetail, ConversationItem, stream_conversation


def create_router(store, tools, *, owner_chat_id=None):
    router = APIRouter()

    @router.post('/api/spine/ask', response_model=AskResponse)
    def ask(body: AskRequest, background: BackgroundTasks):
        question = body.question.strip()
        if not question:
            raise HTTPException(400, '질문이 비어 있습니다')
        refs = [ref.model_dump() for ref in body.attachments or []]
        if any(ref['kind'] != 'doc' for ref in refs):
            raise HTTPException(422, '격리 시험에서는 자료 외 대상 첨부를 지원하지 않습니다')
        refs += [{'kind': 'doc', 'ref': str(i), 'label': ''} for i in body.document_ids or []]
        if body.attachments is None and body.document_ids is None:
            refs = None
        try:
            cid, _ = store.create_question_with_refs(question, conversation_id=body.conversation_id,
                                                    refs=refs, owner_chat_id=owner_chat_id,
                                                    max_new=5 if body.attachments is not None else 12)
        except ConversationNotFound as exc:
            raise HTTPException(404, '대화를 찾을 수 없습니다') from exc
        except DocumentNotFound as exc:
            raise HTTPException(422, '첨부할 수집 자료를 찾을 수 없습니다') from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
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
        if any(r.get('kind') != 'doc' for r in state.get('attached_refs') or []):
            raise HTTPException(422, '격리 시험에서는 기존 복합 첨부 대화를 지원하지 않습니다')
        attached_docs, attached_refs = [], []
        for doc_id in (state.get('attached_doc_ids') or [])[:12]:
            status = store.document_reference_status(conversation_id, doc_id, owner_chat_id=owner_chat_id)
            document = status.get('document') or {}
            title = document.get('title') or f'자료 #{doc_id}'
            if status['available']:
                attached_docs.append({'id': doc_id, 'title': title})
            attached_refs.append({'kind': 'doc', 'ref': str(doc_id), 'label': title,
                                  'available': status['available']})
        return ConversationDetail(id=conversation['id'], title=conversation['title'],
                                  channel=conversation['channel'], attached_documents=attached_docs,
                                  attached_refs=attached_refs, messages=[
            ChatMessage(id=m['id'], role=m['role'], content=m['content'], model=m['model'],
                        citations=json.loads(m['citations_json']) if m['citations_json'] else None,
                        gaps=json.loads(m['gaps_json']) if m['gaps_json'] else None,
                        route=json.loads(m['route_json']) if m['route_json'] else None,
                        attachments=json.loads(m['attachments_json']) if m['attachments_json'] else None,
                        created_at=m['created_at']) for m in messages])

    @router.get('/api/spine/conversations/{conversation_id}/stream')
    async def stream(conversation_id: int):
        try:
            await run_in_threadpool(store.detail, conversation_id, owner_chat_id=owner_chat_id)
        except ConversationNotFound as exc:
            raise HTTPException(404, '대화를 찾을 수 없습니다') from exc
        return await stream_conversation(conversation_id)
    return router
