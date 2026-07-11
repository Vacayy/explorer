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


class KnowledgeItem(BaseModel):
    id: int
    statement: str
    epistemic_status: str
    pace_layer: str
    confidence: float | None
    support: int
    refute: int
    independent: int
    entities: list[str]
    created_at: str


@router.get("/items", response_model=list[KnowledgeItem])
def list_knowledge(status: str = "active"):
    """승격된 지식 목록 (K1 소비·디버그용)."""
    from database import get_connection
    conn = get_connection()
    rows = conn.execute("""
        SELECT k.*, 
               (SELECT count(*) FROM knowledge_evidence WHERE knowledge_id=k.id AND stance='support') sup,
               (SELECT count(*) FROM knowledge_evidence WHERE knowledge_id=k.id AND stance='refute') ref,
               (SELECT count(*) FROM knowledge_evidence WHERE knowledge_id=k.id AND stance='support' AND independent=1) ind
        FROM knowledge k WHERE k.review_status=? ORDER BY k.id DESC""", (status,)).fetchall()
    out = []
    for r in rows:
        ents = [e["name"] for e in conn.execute("""
            SELECT e.name FROM knowledge_entities ke JOIN entities e ON ke.entity_id=e.id
            WHERE ke.knowledge_id=?""", (r["id"],))]
        out.append(KnowledgeItem(
            id=r["id"], statement=r["statement"], epistemic_status=r["epistemic_status"],
            pace_layer=r["pace_layer"], confidence=r["confidence"],
            support=r["sup"], refute=r["ref"], independent=r["ind"],
            entities=ents, created_at=r["created_at"]))
    conn.close()
    return out


@router.post("/items/{knowledge_id}/approve")
def approve_knowledge(knowledge_id: int):
    """승격 승인 — 승인 큐에서 active로 (독립 2+면 corroborated)."""
    from database import get_connection
    conn = get_connection()
    row = conn.execute("SELECT id FROM knowledge WHERE id=? AND review_status='proposed'",
                       (knowledge_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "대기 중인 지식이 없습니다")
    ind = conn.execute("""
        SELECT count(*) FROM knowledge_evidence
        WHERE knowledge_id=? AND stance='support' AND independent=1""", (knowledge_id,)).fetchone()[0]
    epi = "corroborated" if ind >= 2 else "observed"
    conn.execute("UPDATE knowledge SET review_status='active', epistemic_status=? WHERE id=?",
                 (epi, knowledge_id))
    conn.commit()
    conn.close()
    return {"id": knowledge_id, "epistemic_status": epi}


@router.post("/items/{knowledge_id}/reject")
def reject_knowledge(knowledge_id: int):
    from database import get_connection
    conn = get_connection()
    conn.execute("UPDATE knowledge SET review_status='rejected' WHERE id=?", (knowledge_id,))
    conn.commit()
    conn.close()
    return {"id": knowledge_id}
