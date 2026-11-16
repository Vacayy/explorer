"""Read-only captured question routes for isolated trials."""
from fastapi import APIRouter, HTTPException, Response


def create_router(store):
    router=APIRouter(prefix='/api/spine/questions',tags=['spine'])
    @router.get('')
    def listing(narrative_id:int|None=None,status:str|None=None):return store.listing(narrative_id,status)
    @router.get('/proxy/{proxy_id}')
    def proxy(proxy_id:int):
        result=store.proxy(proxy_id)
        if result is None:raise HTTPException(404,'프록시 없음')
        return result
    @router.get('/{question_id}/synthesis')
    def synthesis(question_id:int):
        result=store.synthesis(question_id)
        if result.get('status')=='not_found':raise HTTPException(404,'질문 없음')
        return result
    @router.get('/{question_id}')
    def detail(question_id:int):
        result=store.detail(question_id)
        if 'error' in result:raise HTTPException(404,'질문 없음')
        return result
    @router.delete('/{question_id}',status_code=204)
    def dismiss(question_id:int):
        store.dismiss(question_id)
        return Response(status_code=204)
    return router
