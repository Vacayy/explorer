"""Unchanged legacy admin-decision and screen-computation routes over writable TEMP copies, kept as row overrides.

Loopback-only preview adapter, like the group adapter: the legacy handler runs on one projection
connection whose decision tables are writable TEMP copies; only if it ends 2xx are the rows it
changed stored (`pipeline.postgres_owner_overrides`). A handler that writes any other table hits the
read-only projection and fails the request (fail closed). Agent-proposal approvals that would call a
model or merge entities are refused before the handler runs.
"""
import re

from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from pipeline import postgres_owner_overrides as overrides
from pipeline.postgres_legacy_projection import write_connection_var

ADAPTED = (('POST', '/api/spine/admin/flag'), ('PUT', '/api/spine/regimes/checks/{key}'),
           ('POST', '/api/spine/research/candidates/{candidate_id}/dismiss'),
           ('POST', '/api/spine/agent-proposals/{proposal_id}/approve'),
           ('POST', '/api/spine/agent-proposals/{proposal_id}/dismiss'),
           ('DELETE', '/api/spine/keywords/{keyword_id}'),
           # Screen computations requested on page open (one model call when the cached result is stale).
           ('POST', '/api/spine/stock/{stock_code}/lens/compute'), ('POST', '/api/spine/sources/dossier/summary'),
           ('POST', '/api/spine/beneficiary/upside'), ('POST', '/api/spine/narrative/mer/compute'))
# Approvals whose legacy action only touches the decision tables (alias registration, acknowledgement).
APPROVABLE = {'entity_alias', 'devils_advocate', 'falsifier_watch'}
APPROVE = re.compile(r'^/api/spine/agent-proposals/(\d+)/approve$')


def install(app, projection, factory):
    from routers import (spine_admin, spine_approvals, spine_causal, spine_keywords, spine_lens, spine_narrative,
                         spine_regimes, spine_research, spine_sources)
    from routers.postgres_owner_legacy_fixture import _Borrowed
    wanted = set(ADAPTED)
    for router in (spine_admin.router, spine_regimes.router, spine_research.router, spine_approvals.agent_router,
                   spine_keywords.router, spine_lens.router, spine_sources.router, spine_causal.beneficiary_router,
                   spine_narrative.router):
        for route in router.routes:
            if isinstance(route, APIRoute) and any((method, route.path) in wanted for method in route.methods):
                app.router.routes.append(route)
    patterns = [(method, re.compile('^' + re.sub(r'\\\{[^}]+\\\}', '[^/]+', re.escape(path)) + '$')) for method, path in ADAPTED]

    @app.middleware('http')
    async def owner_decisions(request, call_next):
        if not any(method == request.method and pattern.match(request.url.path) for method, pattern in patterns):
            return await call_next(request)
        from starlette.concurrency import run_in_threadpool
        approve = APPROVE.match(request.url.path)
        if approve:
            def kind():
                conn = projection.connect()
                try:
                    row = conn.execute('SELECT kind FROM agent_proposals WHERE id=?', (int(approve.group(1)),)).fetchone()
                    return row and row['kind']
                finally:
                    conn.close()
            found = await run_in_threadpool(kind)
            if found and found not in APPROVABLE:
                return JSONResponse({'detail': '이 제안의 승인 작업은 후보에서 아직 실행하지 않습니다'}, status_code=409)
        conn, _ = await run_in_threadpool(projection.write_connection)
        try:
            before = overrides.rows(conn)
            token = write_connection_var.set(_Borrowed(conn))
            try:
                response = await call_next(request)
            finally:
                write_connection_var.reset(token)
            if not 200 <= response.status_code < 300:
                return response  # TEMP changes are discarded with the connection

            def store():
                with factory() as pg, pg.transaction():
                    overrides.apply(pg, before, overrides.rows(conn))
            await run_in_threadpool(store)
            return response
        finally:
            conn.close()
