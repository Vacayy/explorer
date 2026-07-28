"""논지 감사 API (thesis audit, docs/specs/thesis-audit.md).

POST /api/spine/thesis/audit   — thesis 주입 → 인과그래프 대질 감사 (read-only, ~수 분 LLM)
GET  /api/spine/thesis/audits  — 감사 히스토리(append-only)
GET  /api/spine/thesis/{id}    — 저장된 감사 결과(재조회 LLM 0)

**read-only**: 사용자 주장은 thesis_audits에 저장될 뿐 인과그래프(온톨로지)에 안 써진다(격리, 등재는 별도·승인).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pipeline.thesis import run_and_store, list_audits, get_audit

router = APIRouter(prefix="/api/spine/thesis", tags=["spine"])


class ThesisIn(BaseModel):
    text: str


@router.post("/audit")
def audit(body: ThesisIn):
    text = (body.text or "").strip()
    if len(text) < 10:
        raise HTTPException(400, "논지가 너무 짧습니다")
    return run_and_store(text)


@router.get("/audits")
def audits():
    return list_audits()


@router.get("/{audit_id}")
def one(audit_id: int):
    r = get_audit(audit_id)
    if not r:
        raise HTTPException(404, "감사 결과 없음")
    return r
