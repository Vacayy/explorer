"""Explicitly mounted isolated study read/annotation routes only."""
from fastapi import APIRouter, BackgroundTasks
from routers.spine_study import Annotation, EditAnnotation, StudyQuestion


def create_router(store, turns=None):
    router = APIRouter(prefix='/api/spine/studies', tags=['study'])

    @router.get('')
    def listing():
        return store.listing()

    @router.get('/{study_id}')
    def read(study_id: int):
        return store.read(study_id)

    @router.post('/{study_id}/annotations')
    def add(study_id: int, body: Annotation):
        return store.add_annotation(study_id, body)

    @router.patch('/{study_id}/annotations/{annotation_id}')
    def edit(study_id: int, annotation_id: int, body: EditAnnotation):
        return store.edit_annotation(study_id, annotation_id, body)

    if turns is not None:
        @router.post('/{study_id}/ask')
        def ask(study_id: int, body: StudyQuestion, background: BackgroundTasks):
            result = turns.queue(study_id,body)
            if result['created']:
                background.add_task(turns.execute,result['id'])
            return result

    return router
