"""문서 디테일 API — 수집한 raw content를 내부 페이지에서 열람 (외부 이동 대신)."""
from pydantic import BaseModel

from fastapi import APIRouter, HTTPException, BackgroundTasks
from database import get_connection
from models.spine import FeedDocument

router = APIRouter(prefix="/api/spine/doc", tags=["spine"])


class RelatedDoc(BaseModel):
    id: int
    source_type: str
    title: str | None
    published_at: str | None
    channel: str | None = None
    similarity: float
    reasons: list[str] = []          # 겹치는 종목·인물·산업 (D-221)


@router.get("/{doc_id}/related", response_model=list[RelatedDoc])
def get_related(doc_id: int):
    """내용 유사 문서 최대 5건 — 아카이브 재방문 촉진 (H2). 규칙은 search.related_docs (D-221)."""
    from pipeline.search import related_docs
    return [RelatedDoc(**d) for d in related_docs(doc_id)]


class ClaimRelated(BaseModel):
    id: int
    source_type: str
    title: str | None
    published_at: str | None
    channel: str | None = None
    quote: str | None = None         # 찾은 대목의 원문 문장 (LLM 작성 아님)
    score: float


class DocClaim(BaseModel):
    claim: str                       # LLM이 뽑은 논점(해석)
    related: list[ClaimRelated]


class DocClaims(BaseModel):
    status: str                      # none | running | ok | failed | skipped
    error: str | None = None
    claims: list[DocClaim] = []


@router.get("/{doc_id}/claims", response_model=DocClaims)
def get_claims(doc_id: int):
    """논점별 관련 자료 (D-233) — 저장분만 읽는다. status=none이면 POST로 만든다."""
    from pipeline.doc_claims import state
    s = state(doc_id)
    if s is None:
        raise HTTPException(404, "문서를 찾을 수 없습니다")
    return DocClaims(**s)


@router.post("/{doc_id}/claims", status_code=202)
def build_claims(doc_id: int, background_tasks: BackgroundTasks):
    """논점 추출(haiku 1회) + 논점별 검색을 백그라운드로. 이미 있거나 진행 중이면 그대로 둔다."""
    from pipeline.doc_claims import execute, queue
    job = queue(doc_id)
    if job["status"] == "missing":
        raise HTTPException(404, "문서를 찾을 수 없습니다")
    if job["token"]:
        background_tasks.add_task(execute, doc_id, job["token"])
    return {"status": job["status"]}


@router.get("/{doc_id}", response_model=FeedDocument)
def get_document(doc_id: int):
    from pipeline.document_read import SQLiteDocumentReader
    result = SQLiteDocumentReader(get_connection).get(doc_id)
    if result is None:
        raise HTTPException(404, "문서를 찾을 수 없습니다")
    return result


@router.post("/{doc_id}/digest", status_code=202)
def generate_digest(doc_id: int, background_tasks: BackgroundTasks):
    from pipeline.youtube_digest import queue, execute
    job = queue(doc_id)
    if job['token']:
        background_tasks.add_task(execute, doc_id, job['token'])
    return {'status': job['status']}
