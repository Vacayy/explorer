from typing import Literal
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field, field_validator
from pipeline import study_projects as projects
from routers.spine_study import AnnotationRef

router=APIRouter(prefix='/api/spine/study-projects',tags=['study'])
class Create(BaseModel):title:str=Field(default='새 스터디',min_length=1,max_length=160)
class Edit(Create):
    note:str=Field(default='',max_length=100000)
    revision:int=Field(gt=0)
class Documents(BaseModel):document_ids:list[int]=Field(min_length=1,max_length=30)
class Clip(BaseModel):
    title:str=Field(min_length=1,max_length=160)
    text:str=Field(min_length=1,max_length=1000000)
    url:str=Field(default='',max_length=2000)
    @field_validator('url')
    @classmethod
    def public_url(cls,value):
        from urllib.parse import urlparse
        if value and (urlparse(value).scheme not in ('https','http') or not urlparse(value).hostname):
            raise ValueError('출처는 http 또는 https URL을 입력해 주세요.')
        return value
class Source(BaseModel):
    study_id:int=Field(gt=0)
    annotations:list[AnnotationRef]=Field(default_factory=list,max_length=30)
class Question(BaseModel):
    question:str=Field(min_length=1,max_length=4000)
    sources:list[Source]=Field(default_factory=list,max_length=10)
    request_key:str=Field(min_length=8,max_length=100)
    context_mode:Literal['auto','selection','continue']='auto'
    research:Literal['auto','off','library','web']='auto'

@router.get('')
def listing():return projects.listing()
@router.post('')
def create(body:Create):return projects.create(body.title)
@router.get('/search')
def search(q:str=''):return projects.search(q)
@router.get('/{pid}')
def read(pid:int):return projects.read(pid)
@router.patch('/{pid}')
def edit(pid:int,body:Edit):return projects.edit(pid,body)
@router.post('/{pid}/documents')
def add(pid:int,body:Documents):return projects.add_documents(pid,body.document_ids)
@router.post('/{pid}/clips')
def clip(pid:int,body:Clip):return projects.add_clip(pid,body)
@router.delete('/{pid}/documents/{sid}')
def remove(pid:int,sid:int):return projects.remove(pid,sid)
@router.post('/{pid}/ask')
def ask(pid:int,body:Question,background:BackgroundTasks):
    result=projects.queue_turn(pid,body)
    if result['created']:background.add_task(projects.execute_turn,result['id'])
    return result
@router.post('/{pid}/turns/{tid}/recover')
def recover(pid:int,tid:int):return projects.recover(pid,tid)
