"""Private fixture router for exercising the existing chat API contract."""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from models.chat_targets import ChatTargetSearch, TargetKind
from starlette.concurrency import run_in_threadpool
from pipeline.postgres_conversations import ConversationNotFound, DocumentNotFound, TargetNotFound
from pipeline.postgres_chat_generation import generate_answer
from routers.spine_ask import AskRequest, AskResponse
from routers.spine_conversations import ChatMessage, ConversationDetail, ConversationItem, TitlePatch, stream_conversation


def create_router(store, tools, *, owner_chat_id=None):
    router = APIRouter()

    @router.get('/api/spine/chat/targets', response_model=ChatTargetSearch)
    def targets(q: str = Query('', max_length=80), kind: TargetKind | None = None):
        if kind not in (None, 'doc', 'stock', 'person'):
            raise HTTPException(422, '격리 시험에서는 자료, 국내 종목, 인물만 지원합니다')
        query = q.strip()
        limit = 20 if kind else 4
        groups = []
        if kind in (None, 'person'):
            items = store.search_person_targets(query, limit=limit)
            if items: groups.append({'kind': 'person', 'items': items})
        if kind in (None, 'stock'):
            items = store.search_stock_targets(query, limit=limit)
            if items: groups.append({'kind': 'stock', 'items': items})
        if kind in (None, 'doc'):
            items = store.search_document_targets(query, limit=limit)
            if items: groups.append({'kind': 'doc', 'items': items})
        return {'query': query, 'kind': kind, 'groups': groups}

    @router.post('/api/spine/ask', response_model=AskResponse)
    def ask(body: AskRequest, background: BackgroundTasks):
        question = body.question.strip()
        if not question:
            raise HTTPException(400, '질문이 비어 있습니다')
        refs = [ref.model_dump() for ref in body.attachments or []]
        if any(ref['kind'] not in ('doc', 'stock', 'person') for ref in refs):
            raise HTTPException(422, '격리 시험에서는 자료, 국내 종목, 인물만 지원합니다')
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
        except TargetNotFound as exc:
            raise HTTPException(422, '첨부할 대상을 찾을 수 없습니다') from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        background.add_task(generate_answer, store, tools, cid, question, owner_chat_id=owner_chat_id,
                            quote=body.quote.model_dump() if body.quote else None,
                            page_context=body.page_context.model_dump() if body.page_context else None)
        return AskResponse(answer=None, citations=[], gaps=[], model=None, conversation_id=cid,
                           status='pending', as_of=datetime.now(timezone.utc).isoformat())

    @router.get('/api/spine/conversations', response_model=list[ConversationItem])
    def list_conversations(limit: int = 20, stock: str | None = None):
        return store.list(owner_chat_id=owner_chat_id, limit=limit, stock=stock)

    @router.patch('/api/spine/conversations/{conversation_id}', response_model=ConversationItem)
    def rename(conversation_id: int, body: TitlePatch):
        title = body.title.strip()[:120]
        if not title:
            raise HTTPException(400, '제목이 비어 있습니다')
        try:
            return store.rename(conversation_id, title, owner_chat_id=owner_chat_id)
        except ConversationNotFound as exc:
            raise HTTPException(404, '대화를 찾을 수 없습니다') from exc

    @router.get('/api/spine/conversations/{conversation_id}', response_model=ConversationDetail)
    def detail(conversation_id: int):
        try:
            conversation, messages = store.detail(conversation_id, owner_chat_id=owner_chat_id)
        except ConversationNotFound as exc:
            raise HTTPException(404, '대화를 찾을 수 없습니다') from exc
        state = json.loads(conversation['state_json'] or '{}')
        if any(r.get('kind') not in ('doc', 'stock', 'person') for r in state.get('attached_refs') or []):
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
        for ref in state.get('attached_refs') or []:
            if ref.get('kind') == 'person':
                with store.connect() as conn:
                    label = store.person_label(conn, ref['ref'])
                attached_refs.append({'kind': 'person', 'ref': str(ref['ref']),
                                      'label': label or ref.get('label') or str(ref['ref']),
                                      'available': bool(label)})
            if ref.get('kind') == 'stock':
                with store.connect() as conn:
                    label = store.stock_label(conn, ref['ref'])
                attached_refs.append({'kind': 'stock', 'ref': str(ref['ref']),
                                      'label': label or ref.get('label') or str(ref['ref']),
                                      'available': bool(label)})
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
