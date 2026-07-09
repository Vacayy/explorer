"""RAG 질의응답 API — 검색된 수집 문서 근거 + 출처 인용 + 갭 분석."""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/spine/ask", tags=["spine"])


class AskRequest(BaseModel):
    question: str


class Citation(BaseModel):
    n: int
    doc_id: int
    title: str
    url: str
    source_type: str
    published_at: str


class Gap(BaseModel):
    type: str    # unsupported | contradiction | stale | missing
    note: str


class AskResponse(BaseModel):
    answer: str | None
    citations: list[Citation]
    gaps: list[Gap]
    model: str | None   # epistemic: 답변은 이 모델의 '가설'
    as_of: str


@router.post("", response_model=AskResponse)
def ask_question(body: AskRequest):
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "질문이 비어 있습니다")
    from pipeline.rag import ask
    try:
        result = ask(q)
    except Exception as e:
        raise HTTPException(502, f"응답 생성 실패: {e}")
    if result.get("error"):
        raise HTTPException(503, result["error"])
    return AskResponse(
        answer=result.get("answer"),
        citations=result.get("citations", []),
        gaps=result.get("gaps", []),
        model=result.get("model"),
        as_of=datetime.now(timezone.utc).isoformat(),
    )
