"""Document claims routes on the PG ledger (single-path candidate); the worker finds related documents."""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.routing import APIRoute

from pipeline import postgres_claims_fixture as claims
from routers.spine_doc import DocClaims


def create_router(factory, run_llm):
    router = APIRouter()

    @router.get('/api/spine/doc/{doc_id}/claims', response_model=DocClaims)
    def get_claims(doc_id: int):
        import database
        legacy = database.get_connection()  # the projection, for related-document metadata
        try:
            with factory() as conn:
                result = claims.state(conn, legacy, doc_id)
        finally:
            legacy.close()
        if result is None:
            raise HTTPException(404, '문서를 찾을 수 없습니다')
        return DocClaims(**result)

    @router.post('/api/spine/doc/{doc_id}/claims', status_code=202)
    def build_claims(doc_id: int, background_tasks: BackgroundTasks):
        with factory() as conn:
            job = claims.queue(conn, doc_id)
        if job['status'] == 'missing':
            raise HTTPException(404, '문서를 찾을 수 없습니다')
        if job['token']:
            background_tasks.add_task(claims.extract, factory, doc_id, job['token'], run_llm)
        return {'status': job['status']}

    return router


def install(app, factory, run_llm):
    """Ahead of the read-only legacy claims route."""
    router = create_router(factory, run_llm)
    owned = {(route.path, method) for route in router.routes for method in route.methods}
    app.router.routes[:] = [route for route in app.router.routes
                            if not (isinstance(route, APIRoute) and any((route.path, m) in owned for m in route.methods))]
    app.router.routes[0:0] = list(router.routes)
