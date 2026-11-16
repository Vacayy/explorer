"""Temporary localhost-only chat/digest rehearsal on an isolated SQLite copy.

Only the original feature routers are registered; no scheduler or unrelated
application startup jobs run. Never attach this service to the public gateway.
"""
from fastapi import FastAPI, HTTPException
import uvicorn

from database import get_connection
from routers import spine_ask, spine_chat_targets, spine_conversations, spine_doc

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


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
               spine_conversations.router, spine_doc.router):
    app.include_router(router)

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)
