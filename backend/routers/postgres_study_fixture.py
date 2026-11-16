"""Explicitly mounted isolated study read/annotation routes only."""
from fastapi import APIRouter, BackgroundTasks
from routers.spine_study import Annotation, EditAnnotation, OpenStudy, StudyQuestion
from models.study_actions import AnnotationActionRequest


def create_router(store, turns=None, actions=None):
    router = APIRouter(prefix='/api/spine/studies', tags=['study'])

    @router.post('')
    def open_document(body: OpenStudy):
        return store.open_document(body.document_id)

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

    if actions is not None:
        @router.get('/{study_id}/actions')
        def list_actions(study_id: int):
            return actions.listing(study_id)

        @router.post('/{study_id}/actions')
        def action(study_id: int, body: AnnotationActionRequest, background: BackgroundTasks):
            result=actions.queue(study_id,body)
            background.add_task(actions.drain,result['owner_key'])
            return result

        @router.post('/{study_id}/actions/resume')
        def resume(study_id: int, background: BackgroundTasks):
            background.add_task(actions.drain,actions.owner_for(study_id))
            return {'ok':True}

        @router.post('/{study_id}/actions/{action_id}/cancel')
        def cancel(study_id: int,action_id: int):
            return actions.cancel(study_id,action_id)

        @router.post('/{study_id}/actions/{action_id}/recover')
        def recover(study_id: int,action_id: int,background: BackgroundTasks):
            result=actions.recover(study_id,action_id)
            background.add_task(actions.drain,actions.owner_for(study_id))
            return result

    if turns is not None:
        @router.post('/{study_id}/ask')
        def ask(study_id: int, body: StudyQuestion, background: BackgroundTasks):
            result = turns.queue(study_id,body)
            if result['created']:
                background.add_task(turns.execute,result['id'])
            return result

        @router.post('/{study_id}/turns/{turn_id}/recover')
        def recover(study_id: int, turn_id: int):
            return turns.recover(study_id,turn_id)

    return router
