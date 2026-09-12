"""Isolated evidence, extraction, review, and comparison routes."""
from typing import Literal
import sqlite3
import json

from fastapi import APIRouter, HTTPException, Query
from models.expectations import EvidenceDocument, EvidencePage
from pipeline import expectation_evidence as evidence
from pipeline import expectation_workflow as workflow, expectation_store as store
from models.expectations import ExtractionRequest, ManualStatement, ReviewStatement, JudgmentNote

router = APIRouter(prefix="/api/experiments/expectations", tags=["expectations-experiment"])


@router.get("/documents", response_model=EvidencePage)
def documents(before_id: int | None = Query(None, ge=1),
              source_type: Literal["blog", "telegram", "youtube"] | None = None,
              product: Literal["hbm", "dram", "nand"] | None = None,
              limit: int = Query(20, ge=1, le=50)):
    try:
        return evidence.list_documents(before_id=before_id, source_type=source_type,
                                       product=product, limit=limit)
    except sqlite3.Error:
        raise HTTPException(503, "실험 자료 저장소를 읽을 수 없습니다") from None


@router.get("/documents/{doc_id}", response_model=EvidenceDocument)
def document(doc_id: int):
    try:
        result = evidence.get_document(doc_id)
    except sqlite3.Error:
        raise HTTPException(503, "실험 자료 저장소를 읽을 수 없습니다") from None
    if result is None:
        raise HTTPException(404, "실험 대상 문서를 찾을 수 없습니다")
    return result


def perform(fn, *args):
    try:
        return fn(*args)
    except workflow.WorkflowError as e:
        raise HTTPException(e.status, str(e)) from None
    except sqlite3.Error:
        raise HTTPException(503, "실험 저장소를 사용할 수 없습니다") from None


@router.post('/extractions', status_code=202)
def extract(body: ExtractionRequest):
    return perform(workflow.launch, body.doc_id)


@router.get('/jobs')
def jobs(doc_id: int = Query(..., ge=1)):
    def fetch():
        with store.connect() as c:
            ids = [r['id'] for r in c.execute('''SELECT j.id FROM jobs j JOIN snapshots p ON p.id=j.snapshot_id
                       WHERE p.doc_id=? ORDER BY j.created_at DESC LIMIT 20''',(doc_id,))]
        return [store.job(jid) for jid in ids]
    return perform(fetch)


@router.get('/jobs/{job_id}')
def job(job_id: str):
    result = perform(store.job,job_id)
    if result is None:
        raise HTTPException(404,'작업이 없습니다')
    return result


@router.post('/jobs/{job_id}/cancel')
def cancel(job_id: str):
    return perform(workflow.cancel,job_id)


@router.get('/statements')
def statements(doc_id: int | None = Query(None, ge=1), status: Literal['draft','approved','rejected'] | None = None):
    return perform(store.list_statements,doc_id,status)


@router.post('/statements', status_code=201)
def manual_statement(body: ManualStatement):
    return perform(workflow.manual,body)


@router.post('/statements/{sid}/review')
def review(sid: int, body: ReviewStatement):
    return perform(workflow.review,sid,body)


@router.get('/statements/{sid}/comparison')
def comparison(sid: int):
    return perform(workflow.compare,sid)


@router.get('/statements/{sid}/evidence', response_model=EvidenceDocument)
def statement_evidence(sid: int):
    def fetch():
        with store.connect() as c:
            row=c.execute('''SELECT p.data FROM snapshots p JOIN statements s
                             ON s.snapshot_id=p.id WHERE s.id=?''',(sid,)).fetchone()
        if row is None:
            raise workflow.WorkflowError('발언이 없습니다',404)
        return json.loads(row['data'])
    return perform(fetch)


@router.get('/statements/{sid}/history')
def history(sid: int):
    def fetch():
        if not store.get_statement(sid):
            raise workflow.WorkflowError('발언이 없습니다',404)
        with store.connect() as c:
            return {'reviews':[dict(r) | {'data':json.loads(r['data'])} for r in c.execute(
                        'SELECT * FROM reviews WHERE statement_id=? ORDER BY id DESC',(sid,))],
                    'notes':[dict(r) for r in c.execute('SELECT * FROM notes WHERE statement_id=? ORDER BY id DESC',(sid,))]}
    return perform(fetch)


@router.post('/statements/{sid}/notes', status_code=201)
def add_note(sid: int, body: JudgmentNote):
    def save():
        if not body.text.strip():
            raise workflow.WorkflowError('메모가 비어 있습니다')
        if not store.get_statement(sid):
            raise workflow.WorkflowError('발언이 없습니다',404)
        with store.connect() as c:
            nid=c.execute('INSERT INTO notes(statement_id,text) VALUES (?,?)',(sid,body.text.strip())).lastrowid
        return {'id':nid}
    return perform(save)


from models.expectations import ReadingPage, ReadingHistory
from pipeline import expectation_reading


@router.get('/reading', response_model=ReadingPage)
def reading(days: int = Query(7, ge=1, le=30),
            product: Literal['hbm', 'dram', 'nand'] | None = None,
            source_type: Literal['blog', 'telegram', 'youtube'] | None = None):
    if days not in (1, 7, 30):
        raise HTTPException(422, '기간은 1일, 7일, 30일 중 선택하세요')
    return perform(lambda: expectation_reading.reading(days=days, product=product, source_type=source_type))


@router.get('/reading/{doc_id}/history', response_model=ReadingHistory)
def reading_history(doc_id: int):
    return perform(expectation_reading.history, doc_id)
