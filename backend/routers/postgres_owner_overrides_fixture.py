"""Unchanged legacy admin-decision and screen-computation routes over writable TEMP copies, kept as row overrides.

Loopback-only preview adapter, like the group adapter: the legacy handler runs on one projection
connection whose decision tables are writable TEMP copies; only if it ends 2xx are the rows it
changed stored (`pipeline.postgres_owner_overrides`). A handler that writes any other table hits the
read-only projection and fails the request (fail closed). Narrative generation also gets writable
graph copies, and its graph diff is published with the result (`pipeline.postgres_graph_compute`).
Agent-proposal approvals that would call a model or merge entities are refused before the handler runs.
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
           ('POST', '/api/spine/beneficiary/upside'), ('POST', '/api/spine/narrative/mer/compute'),
           ('POST', '/api/spine/narrative/compute'),
           # Button computations over the candidate's own material (no external requests).
           ('POST', '/api/spine/person/{name}/profile'), ('POST', '/api/spine/narrative/scenario/compute'),
           ('POST', '/api/spine/report/compute'), ('POST', '/api/spine/trade/{hs_code}/beneficiaries'),
           ('POST', '/api/spine/research/candidates/{candidate_id}/approve'),
           ('POST', '/api/spine/regimes/commentary'), ('POST', '/api/spine/thesis/audit'),
           ('POST', '/api/spine/world/big-picture/rebuild'),
           ('POST', '/api/spine/company/{name}/profile'), ('POST', '/api/spine/knowledge/worldview/compute'),
           ('POST', '/api/spine/pricing/extract'),
           # Saved prices answer (fetches skipped offline, kept as not-run requests); the model call stays.
           ('POST', '/api/spine/transcript/detail/{transcript_id}/digest'),  # sets transcripts.digest once
           ('POST', '/api/spine/transcript/detail/{transcript_id}/reaction'),
           ('POST', '/api/spine/transcript/expectation/{ticker}'))
# Computations that also write the graph: graph tables are copied writable and their diff is published.
GRAPH_WRITERS = {'/api/spine/narrative/compute', '/api/spine/narrative/scenario/compute'}
# Computations that record their runs and read them back (cooldown, budget): job_runs is copied writable and
# the rows they add are kept in the candidate's own run ledger (`pipeline.postgres_candidate_job_runs`).
RUN_RECORDERS = {'/api/spine/world/big-picture/rebuild'}
# Approvals whose legacy action only touches the decision tables (alias registration, acknowledgement).
APPROVABLE = {'entity_alias', 'devils_advocate', 'falsifier_watch'}
APPROVE = re.compile(r'^/api/spine/agent-proposals/(\d+)/approve$')


def install(app, projection, factory):
    from routers import (spine_admin, spine_approvals, spine_causal, spine_company, spine_keywords, spine_knowledge,
                         spine_lens, spine_narrative, spine_person, spine_pricing, spine_regimes, spine_report, spine_research,
                         spine_sources, spine_thesis, spine_trade, spine_transcript, spine_world)
    from routers.postgres_owner_legacy_fixture import _Borrowed
    wanted = set(ADAPTED)
    for router in (spine_admin.router, spine_regimes.router, spine_research.router, spine_approvals.agent_router,
                   spine_keywords.router, spine_lens.router, spine_sources.router, spine_causal.beneficiary_router,
                   spine_narrative.router, spine_person.router, spine_report.router, spine_trade.router,
                   spine_thesis.router, spine_world.router, spine_transcript.router, spine_company.router,
                   spine_knowledge.router, spine_pricing.router):
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
        from pipeline import postgres_graph_compute as graph
        from pipeline import postgres_candidate_job_runs as job_runs
        writes_graph = request.url.path in GRAPH_WRITERS
        records_runs = request.url.path in RUN_RECORDERS
        from routers.postgres_legacy_read_fixture import _offline
        offline = _offline.set(True)  # in-process network guard; model calls run as CLI subprocesses
        extra = (graph.GRAPH if writes_graph else ()) + (('job_runs',) if records_runs else ())
        conn, _ = await run_in_threadpool(projection.write_connection, extra)
        try:
            before = overrides.rows(conn)
            runs_floor = job_runs.floor(conn) if records_runs else None
            graph_before = await run_in_threadpool(graph.snapshot, conn) if writes_graph else None
            token = write_connection_var.set(_Borrowed(conn))
            try:
                response = await call_next(request)
            finally:
                write_connection_var.reset(token)
            if not 200 <= response.status_code < 300:
                return response  # TEMP changes are discarded with the connection

            def store():
                with factory() as pg, pg.transaction():
                    overrides.apply(pg, before, overrides.rows(conn), source=f'{request.method} {request.url.path}')
                    if writes_graph:
                        graph.publish(pg, graph_before, graph.snapshot(conn), run_id=f'compute:{request.url.path}')
                    if records_runs:
                        job_runs.capture(pg, conn, runs_floor, f'{request.method} {request.url.path}')
            await run_in_threadpool(store)
            return response
        finally:
            conn.close()
            _offline.reset(offline)
