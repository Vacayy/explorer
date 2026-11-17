"""Operational observation on the candidate: request counts, screen usage events and the admin observe summary.

Same behaviour as the legacy app (main.py's request middleware, routers.spine_observe), with the logs on PG
(pipeline.postgres_observe_ledgers, pipeline.postgres_llm_calls, pipeline.postgres_client_errors). The summary is
the unchanged legacy one, computed on one connection that carries the logs; it answers 503 rather than a false
zero while any log is missing.
"""
import asyncio
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse

from models.observe import ObserveSummary, UsageBatch
from pipeline import postgres_observe_ledgers as ledgers

BODY_LIMIT = 64 * 1024


class BoundedRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def bounded(request: Request):
            if request.method == 'POST':
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > BODY_LIMIT:
                        return JSONResponse({'detail': 'Request too large'}, status_code=413)
                    chunks.append(chunk)
                request._body = b''.join(chunks)
            return await original(request)
        return bounded


def install(app, projection, factory):
    """`projection`: returns the LegacyProjection (created after the routes)."""
    from pipeline import observe
    from pipeline.postgres_legacy_projection import write_connection_var
    from routers.postgres_owner_legacy_fixture import _Borrowed
    router = APIRouter(route_class=BoundedRoute)
    observe.flush = lambda *args, **kwargs: ledgers.flush(factory)  # the legacy summary flushes first: to PG here

    @router.post('/api/spine/usage', status_code=204)
    def usage(body: UsageBatch):
        with factory() as conn:
            if conn.execute("SELECT to_regclass('usage_events')").fetchone()[0] is None:
                raise HTTPException(503, 'Usage log unavailable')
        ledgers.save_events(factory, [e.model_dump() for e in body.events])

    @router.get('/api/spine/admin/observe', response_model=ObserveSummary)
    def observe_summary(days: int = 7):
        days = max(1, min(days, 90))
        with factory() as conn:
            if not ledgers.ready(conn):
                raise HTTPException(503, 'Observation logs unavailable')
        ledgers.flush(factory)  # the counts still in memory, before the copies are taken
        conn = ledgers.observe_connection(projection(), factory, days)
        token = write_connection_var.set(_Borrowed(conn))
        try:
            return observe.summary(days)
        finally:
            write_connection_var.reset(token)
            conn.close()

    app.include_router(router)

    @app.on_event('shutdown')
    def flush_on_shutdown():
        ledgers.flush(factory)  # the last minute of counts survives a restart (legacy main.py)

    @app.middleware('http')
    async def observe_requests(request, call_next):
        """Legacy main.py: requests by route pattern, status class and duration bucket, summed hourly."""
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get('route')
            if request.headers.get('x-observe-skip') != '1':  # the contract checks are not usage
                observe.record_request(request.method, getattr(route, 'path', None) or '(unmatched)', status,
                                       (time.perf_counter() - started) * 1000)
            if observe.claim_flush():
                asyncio.get_running_loop().run_in_executor(None, ledgers.flush, factory)
