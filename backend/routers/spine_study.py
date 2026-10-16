"""Study mutations are explicit. Reading never generates or imports content."""
from typing import Literal
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field
from pipeline import study
from pipeline import study_actions
from models.study_actions import AnnotationActionRequest

router=APIRouter(prefix='/api/spine/studies',tags=['study'])
class OpenStudy(BaseModel):
    document_id:int=Field(gt=0)
class Annotation(BaseModel):
    kind:Literal['highlight','comment']
    start:int=Field(ge=0)
    end:int=Field(gt=0)
    exact:str=Field(min_length=1,max_length=30000)
    comment:str=Field(default='',max_length=10000)
class EditAnnotation(BaseModel):
    revision:int=Field(gt=0)
    comment:str=Field(default='',max_length=10000)
    delete:bool=False
class AnnotationRef(BaseModel):
    id:int=Field(gt=0)
    revision:int=Field(gt=0)
class StudyQuestion(BaseModel):
    question:str=Field(default='',max_length=4000)
    action:Literal['question','summarize']='question'
    annotations:list[AnnotationRef]=Field(default_factory=list,max_length=30)
    request_key:str=Field(min_length=8,max_length=100)
    context_mode:Literal['auto','selection','continue']='auto'
    research:Literal['auto','off','library','web']='auto'

@router.post('')
def open_study(body:OpenStudy):return study.open_document(body.document_id)
@router.get('')
def list_studies():return study.list_studies()
@router.get('/{study_id}')
def read_study(study_id:int):return study.read_study(study_id)
@router.post('/{study_id}/annotations')
def add(study_id:int,body:Annotation):return study.add_annotation(study_id,body)
@router.patch('/{study_id}/annotations/{annotation_id}')
def edit(study_id:int,annotation_id:int,body:EditAnnotation):return study.edit_annotation(study_id,annotation_id,body)
@router.post('/{study_id}/ask')
def ask(study_id:int,body:StudyQuestion,background:BackgroundTasks):
    result=study.queue_turn(study_id,body)
    if result['created']:background.add_task(study.execute_turn,result['id'])
    return result

@router.post('/{study_id}/turns/{turn_id}/recover')
def recover(study_id:int,turn_id:int):return study.recover_turn(study_id,turn_id)

@router.get('/{study_id}/actions')
def actions(study_id:int):return study_actions.list_actions(study_id)

@router.post('/{study_id}/actions')
def act(study_id:int,body:AnnotationActionRequest,background:BackgroundTasks):
    result=study_actions.queue_action(study_id,body)
    background.add_task(study_actions.drain,result['owner_key'])
    return result

@router.post('/{study_id}/actions/resume')
def resume_actions(study_id:int,background:BackgroundTasks):
    background.add_task(study_actions.drain,study_actions.owner_for(study_id))
    return {'ok':True}

@router.post('/{study_id}/actions/{action_id}/cancel')
def cancel_action(study_id:int,action_id:int):return study_actions.cancel(study_id,action_id)

@router.post('/{study_id}/actions/{action_id}/recover')
def recover_action(study_id:int,action_id:int,background:BackgroundTasks):
    result=study_actions.recover(study_id,action_id)
    background.add_task(study_actions.drain,study_actions.owner_for(study_id))
    return result
