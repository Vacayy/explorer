"""Temporary localhost-only chat/digest rehearsal on an isolated SQLite copy.

Only the original feature routers are registered; no scheduler or unrelated
application startup jobs run. Never attach this service to the public gateway.
"""
from fastapi import FastAPI
import uvicorn

from routers import spine_ask, spine_chat_targets, spine_conversations, spine_doc

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
for router in (spine_ask.router, spine_chat_targets.router,
               spine_conversations.router, spine_doc.router):
    app.include_router(router)

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)
