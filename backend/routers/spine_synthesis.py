"""문서 교차 종합 API (D-104, docs/specs/doc-synthesis.md).

저장됨에서 고른 문서 묶음 → 교차 종합(sonnet). read-only 산출물 — 그래프·트래커 무변경.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pipeline.doc_synthesis import MAX_DOCS, create_synthesis, get_synthesis, list_syntheses

router = APIRouter(prefix="/api/spine/synthesis", tags=["spine"])


class SynthesizeRequest(BaseModel):
    doc_ids: list[int]


@router.get("")
def api_list(limit: int = 20):
    return list_syntheses(limit=limit)


@router.get("/{synthesis_id}")
def api_get(synthesis_id: int):
    row = get_synthesis(synthesis_id)
    if not row:
        raise HTTPException(404, "종합을 찾을 수 없습니다")
    return row


@router.post("", status_code=201)
def api_create(body: SynthesizeRequest):
    ids = list(dict.fromkeys(body.doc_ids))
    if len(ids) < 2:
        raise HTTPException(400, "문서 2건 이상을 골라주세요")
    if len(ids) > MAX_DOCS:
        raise HTTPException(400, f"한 번에 최대 {MAX_DOCS}건까지 엮을 수 있습니다")
    result = create_synthesis(ids)
    status = result.get("status")
    if status == "unavailable":
        raise HTTPException(503, "LLM 엔진을 사용할 수 없습니다")
    if status == "empty":
        raise HTTPException(400, "본문이 있는 문서가 2건 이상이어야 합니다")
    if status != "ok":
        raise HTTPException(502, "종합 생성 실패")
    return result
