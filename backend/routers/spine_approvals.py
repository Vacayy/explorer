"""승인 큐 API — 기계의 제안이 사람의 결정을 기다리는 곳 (판단 루프 ③).

유형별로 확장된다: alias(별칭 제안) → knowledge(지식 승격, K0) → …
승인/거부 실행은 각 유형의 기존 API를 재사용 — 이 라우터는 집계·노출만.
"""
import json

from fastapi import APIRouter
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/approvals", tags=["spine"])
agent_router = APIRouter(prefix="/api/spine/agent-proposals", tags=["spine"])


class AgentActionResult(BaseModel):
    status: str
    kind: str | None = None
    result: dict | None = None


@agent_router.post("/{proposal_id}/approve", response_model=AgentActionResult)
def approve_agent_proposal(proposal_id: int):
    """승인 — kind별 액션 (neglect=opus 브리프, contested_edge=opus 조정, 나머지=확인)."""
    from pipeline.agent_proposals import approve_proposal
    return AgentActionResult(**approve_proposal(proposal_id))


@agent_router.post("/{proposal_id}/dismiss", response_model=AgentActionResult)
def dismiss_agent_proposal(proposal_id: int):
    from pipeline.agent_proposals import dismiss_proposal
    return AgentActionResult(**dismiss_proposal(proposal_id))


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
    # 에이전트 제안함 (진화계획 3단계 v1) — kind 그대로 노출, 승인/기각은 /agent-proposals API
    for r in conn.execute("""
        SELECT id, kind, title, rationale, payload_json FROM agent_proposals
        WHERE status='proposed' ORDER BY detected_at DESC
    """):
        payload = json.loads(r["payload_json"] or "{}")
        items.append(ApprovalItem(
            kind=r["kind"], id=r["id"], title=r["title"], detail=r["rationale"],
            entity_name=None, stock_code=payload.get("stock_code")))
    LAYER_KO = {"cycle": "사이클", "structure": "구조", "regime": "제도"}
    for r in conn.execute("""
        SELECT k.id, k.statement, k.pace_layer,
               (SELECT count(*) FROM knowledge_evidence WHERE knowledge_id=k.id AND stance='support' AND independent=1) ind,
               (SELECT count(*) FROM knowledge_evidence WHERE knowledge_id=k.id AND stance='refute') ref,
               (SELECT e.name FROM knowledge_entities ke JOIN entities e ON ke.entity_id=e.id
                WHERE ke.knowledge_id=k.id LIMIT 1) ename,
               (SELECT e.aliases FROM knowledge_entities ke JOIN entities e ON ke.entity_id=e.id
                WHERE ke.knowledge_id=k.id LIMIT 1) scode
        FROM knowledge k WHERE k.review_status='proposed' ORDER BY k.created_at DESC
    """):
        detail = f"{LAYER_KO.get(r['pace_layer'], r['pace_layer'])}층 · 독립 관측 {r['ind']}건"
        if r["ref"]:
            detail += f" · ⚠반박 {r['ref']}건"
        items.append(ApprovalItem(
            kind="knowledge", id=r["id"],
            title=r["statement"][:80],
            detail=detail, entity_name=r["ename"], stock_code=r["scode"]))
    conn.close()
    return items
