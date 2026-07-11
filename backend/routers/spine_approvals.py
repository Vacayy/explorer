"""승인 큐 API — 기계의 제안이 사람의 결정을 기다리는 곳 (판단 루프 ③).

유형별로 확장된다: alias(별칭 제안) → knowledge(지식 승격, K0) → …
승인/거부 실행은 각 유형의 기존 API를 재사용 — 이 라우터는 집계·노출만.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/approvals", tags=["spine"])


class ApprovalItem(BaseModel):
    kind: str            # alias | knowledge(예정)
    id: int              # 유형별 대상 id (alias면 entity_keywords.id)
    title: str           # "삼성전자 ← \'삼전\'"
    detail: str | None   # 부가 설명
    entity_name: str | None
    stock_code: str | None


@router.get("", response_model=list[ApprovalItem])
def list_approvals():
    conn = get_connection()
    items = []
    for r in conn.execute("""
        SELECT ek.id, ek.keyword, e.name, e.aliases stock_code
        FROM entity_keywords ek JOIN entities e ON ek.entity_id = e.id
        WHERE ek.status = 'proposed' ORDER BY ek.created_at DESC
    """):
        items.append(ApprovalItem(
            kind="alias", id=r["id"],
            title=f"{r['name']} ← '{r['keyword']}'",
            detail="LLM이 발견한 별칭 — 승인 시 매칭 기준에 편입되고 기존 문서에 소급 링크",
            entity_name=r["name"], stock_code=r["stock_code"]))
    conn.close()
    return items
