"""Explicitly mounted project routes for private PG study trials."""
from fastapi import APIRouter, BackgroundTasks
from routers.spine_study_projects import Create, Edit, Documents, Clip, Question


def create_router(store, turns=None):
    router = APIRouter(prefix='/api/spine/study-projects',tags=['study'])
    @router.get('')
    def listing(): return store.listing()
    @router.post('')
    def create(body: Create): return store.create(body.title)
    @router.get('/search')
    def search(q: str = ''): return store.search(q)
    @router.get('/{pid}')
    def read(pid: int): return store.read(pid)
    @router.patch('/{pid}')
    def edit(pid: int, body: Edit): return store.edit(pid,body)
    @router.post('/{pid}/documents')
    def add(pid: int, body: Documents): return store.add_documents(pid,body.document_ids)
    @router.post('/{pid}/clips')
    def clip(pid: int, body: Clip): return store.add_clip(pid,body)
    @router.delete('/{pid}/documents/{sid}')
    def remove(pid: int,sid: int): return store.remove(pid,sid)
    if turns is not None:
        @router.post('/{pid}/ask')
        def ask(pid: int, body: Question, background: BackgroundTasks):
            result=turns.queue(pid,body,project=True)
            if result['created']:
                background.add_task(turns.execute,result['id'],project=True)
            return result
        @router.post('/{pid}/turns/{tid}/recover')
        def recover(pid: int, tid: int):
            return turns.recover(pid,tid,project=True)
    return router
