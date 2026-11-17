"""The screen API error report (POST /api/spine/client-errors) on the candidate PG log.

Same request and 204 as the legacy route; the request body is capped before parsing. Reading the log stays the
legacy GET (through the projection's TEMP copy, pipeline.postgres_client_errors.derive).
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse

from models.client_errors import ClientErrorReport
from pipeline import postgres_client_errors as log

BODY_LIMIT = 16 * 1024


class BoundedRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def bounded(request: Request):
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > BODY_LIMIT:
                    return JSONResponse({'detail': 'Request too large'}, status_code=413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
            return await original(request)
        return bounded


def create_router(factory):
    router = APIRouter(route_class=BoundedRoute)

    @router.post('/api/spine/client-errors', status_code=204)
    def report(body: ClientErrorReport):
        with factory() as conn:
            if not log.ready(conn):
                raise HTTPException(503, 'Error log unavailable')
            log.record(conn, body)

    return router
