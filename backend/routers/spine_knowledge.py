"""지식 주입 API — 대화·옴니바·봇의 공용 입구 (knowledge-system.md ①)."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/spine/knowledge", tags=["spine"])


class InjectRequest(BaseModel):
    content: str
    epistemic: str = "hypothesis"   # fact | hypothesis


class InjectResponse(BaseModel):
    doc_id: int | None
    title: str
    epistemic: str
    entities: list[str]


@router.post("", response_model=InjectResponse, status_code=201)
def inject(body: InjectRequest):
    from pipeline.knowledge import inject_knowledge
    try:
        r = inject_knowledge(body.content, body.epistemic)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return InjectResponse(**r)
