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
def index(narrative_id: int | None = None, status: str | None = None):
    """미결 질문 목록 (판정 배지용, LLM 0). narrative_id·status 필터. apiQuery 패턴 배열 반환."""
    from pipeline.questions import list_questions
    return list_questions(narrative_id=narrative_id, status=status)


class FromDocRequest(BaseModel):
    doc_id: int


@router.post("/from-doc")
def from_doc(body: FromDocRequest):
    """Q5 — 단일 소스 문서에서 딥다이브 핵심질문 후보 + 파급 event 도출 (sonnet, ~수십 초). 생성은 별도(질문 픽·시나리오)."""
    from pipeline.questions import derive_questions_from_doc
    r = derive_questions_from_doc(body.doc_id)
    if "error" in r:
        raise HTTPException(503, r["error"])
    return r


class ScenarioRequest(BaseModel):
    event: str


@router.post("/{question_id}/scenario")
def scenario(question_id: int, body: ScenarioRequest):
    """Q5 — 질문에 묶어 파급 시나리오 생성+캐시 (opus, ~수 분). 질문=허브(D-070): 질문 상세에서 열람."""
    from pipeline.questions import run_scenario_for_event
    r = run_scenario_for_event(body.event, question_id=question_id)
    if "error" in r:
        raise HTTPException(503, r["error"])
    return r


@router.post("/propose")
def propose(limit: int = 3):
    """지배 내러티브에서 질문 후보 자동 도출 (생성자 ①, 제안 큐 — 분해는 승인 후)."""
    from pipeline.questions import propose_from_narratives
    return propose_from_narratives(limit=limit)


@router.post("/{question_id}/approve")
def approve(question_id: int):
    """제안 질문 승인 → 분해·추적 시작 (비싼 분해는 승인 뒤, ~수 분)."""
    from pipeline.questions import approve_question
    r = approve_question(question_id)
    if "error" in r:
        raise HTTPException(404, r["error"])
    return r


@router.get("/{question_id}")
def detail(question_id: int):
    """질문 트리 — 서브질문 → 프록시 → 관측 시계열 + 판정 (LLM 0). 조회 시 last_viewed_at 갱신(활성 신호, D-072)."""
    from database import get_connection
    from pipeline.questions import get_tree
    r = get_tree(question_id)
    if "error" in r:
        raise HTTPException(404, r["error"])
    conn = get_connection()
    conn.execute("UPDATE questions SET last_viewed_at=datetime('now') WHERE id=?", (question_id,))
    conn.commit()
    conn.close()
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
