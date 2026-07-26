"""핵심질문 트래커 API (D-067·D-068, docs/specs/question-proxy.md).

질문 주입(자동분해) → 트리 조회 → 판정 롤업. 생성자 ②(사용자 주입)가 Phase 1 본진.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/spine/questions", tags=["spine"])


class AskRequest(BaseModel):
    text: str
    narrative_id: int | None = None
    source_doc_id: int | None = None


@router.post("", status_code=201)
def create(body: AskRequest):
    """질문 주입 → LLM 자동분해(서브질문·프록시) → numeric 프록시 추출 → 트리 반환 (생성자 ②)."""
    from pipeline.questions import decompose_question
    if not body.text.strip():
        raise HTTPException(400, "질문이 비어 있습니다")
    r = decompose_question(body.text, created_by="user",
                           narrative_id=body.narrative_id, source_doc_id=body.source_doc_id)
    if "error" in r:
        raise HTTPException(503, r["error"])
    return r


@router.get("")
def index():
    """미결 질문 목록 (판정 배지용, LLM 0)."""
    from pipeline.questions import list_questions
    return {"questions": list_questions()}


@router.get("/{question_id}")
def detail(question_id: int):
    """질문 트리 — 서브질문 → 프록시 → 관측 시계열 + 판정 (LLM 0)."""
    from pipeline.questions import get_tree
    r = get_tree(question_id)
    if "error" in r:
        raise HTTPException(404, r["error"])
    return r


@router.post("/{question_id}/rollup")
def recompute(question_id: int):
    """판정 재롤업 — 관측 갱신 후 호출(재료 없으면 no-op·결정적, 판정 변화 시만 haiku)."""
    from pipeline.questions import rollup
    r = rollup(question_id)
    if "error" in r:
        raise HTTPException(404, r["error"])
    return r


@router.delete("/{question_id}", status_code=204)
def remove(question_id: int):
    from pipeline.questions import dismiss_question
    dismiss_question(question_id)
