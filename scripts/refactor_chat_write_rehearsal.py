"""Temporary localhost-only chat/digest rehearsal on an isolated SQLite copy.

Only the original feature routers are registered; no scheduler or unrelated
application startup jobs run. Never attach this service to the public gateway.
"""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from fastapi import BackgroundTasks, FastAPI, HTTPException, Response
from fastapi.encoders import jsonable_encoder
import uvicorn

from database import get_connection
from routers import spine_ask, spine_chat_targets, spine_conversations, spine_doc, spine_questions, spine_study, spine_study_projects

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def same_video(source: dict, copy: dict) -> bool:
    """Reject ambiguous IDs or changed transcripts across snapshot stores."""
    return (source.get('source_type') == copy.get('source_type') == 'youtube'
            and bool(source.get('url')) and bool(source.get('transcript'))
            and all(source.get(key) == copy.get(key)
                    for key in ('id', 'url', 'title', 'published_at', 'transcript')))


def source_document(doc_id: int, generation: str | None = None):
    url = f'http://explorer-refactor-durable-candidate:8000/api/spine/doc/{doc_id}'
    if generation:
        url += '?' + urlencode({'generation': generation})
    try:
        with urlopen(url, timeout=30) as upstream:
            return json.load(upstream), {
                k: v for k, v in upstream.headers.items()
                if k.lower().startswith('x-explorer-')
            }
    except HTTPError as exc:
        raise HTTPException(exc.code, '원본 문서를 조회할 수 없습니다') from exc
    except (URLError, TimeoutError) as exc:
        raise HTTPException(503, '원본 문서를 조회할 수 없습니다') from exc


def copied_document(doc_id: int):
    try:
        return jsonable_encoder(spine_doc.get_document(doc_id))
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise


def check_study_document(doc_id: int):
    source, _ = source_document(doc_id)
    copy = copied_document(doc_id)
    keys = ('id', 'source_type', 'url', 'title', 'published_at', 'content')
    if not copy or not source.get('content') or any(source.get(k) != copy.get(k) for k in keys):
        raise HTTPException(409, '미리보기와 스터디 사본의 문서가 달라 추가할 수 없습니다')


@app.post('/api/spine/studies')
def open_study(body: spine_study.OpenStudy):
    check_study_document(body.document_id)
    return spine_study.open_study(body)


@app.post('/api/spine/study-projects/{pid}/documents')
def add_study_documents(pid: int, body: spine_study_projects.Documents):
    for doc_id in body.document_ids:
        check_study_document(doc_id)
    return spine_study_projects.add(pid, body)


@app.post('/api/spine/questions', status_code=201)
def create_question(body: spine_questions.AskRequest):
    if body.source_doc_id is not None:
        check_study_document(body.source_doc_id)
    # Keep original decomposition, related observation extraction and rollup.
    return spine_questions.create(body)


@app.get('/api/spine/doc/{doc_id}')
def document(doc_id: int, response: Response, generation: str | None = None):
    source, headers = source_document(doc_id, generation)
    for key, value in headers.items():
        response.headers[key] = value
    # Pinned generations remain immutable; an overlay is only for the current
    # unpinned view and only when the original video/transcript still matches.
    if not generation and source.get('source_type') == 'youtube' and source.get('digest_status') != 'ok':
        copy = copied_document(doc_id)
        if copy and same_video(source, copy) and copy.get('digest_status') in ('generating', 'failed', 'ok'):
            for key in ('digest_status', 'digest_error', 'video_digest', 'transcript'):
                source[key] = copy.get(key)
    return source


@app.post('/api/spine/doc/{doc_id}/digest', status_code=202)
def digest(doc_id: int, background: BackgroundTasks):
    source, _ = source_document(doc_id)
    copy = copied_document(doc_id)
    if not copy or not same_video(source, copy):
        raise HTTPException(409, '미리보기와 작업 사본의 영상 또는 자막이 달라 정리할 수 없습니다')
    return spine_doc.generate_digest(doc_id, background)


@app.get('/api/spine/conversations/{conversation_id}')
def owner_conversation(conversation_id: int):
    # Match the existing read-only viewer's ownership check for direct reads.
    owner_sql, owner_params = spine_conversations._owner_filter()
    conn = get_connection()
    try:
        visible = conn.execute(
            f'SELECT 1 FROM conversations c WHERE c.id=? AND {owner_sql}',
            (conversation_id, *owner_params),
        ).fetchone()
    finally:
        conn.close()
    if not visible:
        raise HTTPException(404, '대화를 찾을 수 없습니다')
    return spine_conversations.get_conversation(conversation_id)


for router in (spine_ask.router, spine_chat_targets.router,
               spine_conversations.router, spine_doc.router, spine_questions.router,
               spine_study.router, spine_study_projects.router):
    app.include_router(router)

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)
