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


class Worldview(BaseModel):
    status: str          # fresh | cached | empty | unavailable | failed
    briefing: str | None
    created_at: str | None
    stale: bool = False


@router.get("/worldview", response_model=Worldview)
def get_worldview():
    """캐시된 세계관 브리핑 + stale 플래그 — LLM 호출 없음 (도시에 2단 패턴)."""
    from database import get_connection
    from pipeline.worldview import gather, get_cached, inputs_hash
    conn = get_connection()
    m = gather(conn)
    cached = get_cached(conn)
    conn.close()
    if not m["knowledge"]:
        return Worldview(status="empty", briefing=None, created_at=None)
    stale = not cached or cached["doc_ids_hash"] != inputs_hash(m)
    if not cached:
        return Worldview(status="empty", briefing=None, created_at=None, stale=True)
    return Worldview(status="cached", briefing=cached["digest"],
                     created_at=cached["created_at"], stale=stale)


@router.post("/worldview/compute", response_model=Worldview)
def compute_worldview_endpoint():
    """입력(지식 상태·주간 신호·관측)이 바뀐 경우에만 sonnet 생성 — 멱등."""
    from pipeline.worldview import compute_worldview
    r = compute_worldview()
    return Worldview(status=r["status"], briefing=r.get("briefing"), created_at=r.get("created_at"))


class KnowledgeEntity(BaseModel):
    name: str
    type: str
    aliases: str | None   # company면 종목코드 (도시에 링크)


class KnowledgeItem(BaseModel):
    id: int
    statement: str
    epistemic_status: str
    pace_layer: str
    confidence: float | None
    support: int
    refute: int
    independent: int
    activation: float | None   # 조회 시 계산 (A-2) — 죽은 지식은 뒤로
    entities: list[KnowledgeEntity]
    created_at: str
    contested_at: str | None


@router.get("/items", response_model=list[KnowledgeItem])
def list_knowledge(status: str = "active"):
    """승격된 지식 목록 — 지식 익스플로러·K1 소비. activation 내림차순."""
    from database import get_connection
    from pipeline.consolidation import activation as _activation
    conn = get_connection()
    rows = conn.execute("""
        SELECT k.*,
               (SELECT count(*) FROM knowledge_evidence WHERE knowledge_id=k.id AND stance='support') sup,
               (SELECT count(*) FROM knowledge_evidence WHERE knowledge_id=k.id AND stance='refute') ref,
               (SELECT count(*) FROM knowledge_evidence WHERE knowledge_id=k.id AND stance='support' AND independent=1) ind
        FROM knowledge k WHERE k.review_status=? ORDER BY k.id DESC""", (status,)).fetchall()
    out = []
    for r in rows:
        ents = [KnowledgeEntity(name=e["name"], type=e["type"], aliases=e["aliases"])
                for e in conn.execute("""
            SELECT e.name, e.type, e.aliases FROM knowledge_entities ke
            JOIN entities e ON ke.entity_id=e.id WHERE ke.knowledge_id=?""", (r["id"],))]
        obs = [x["observed_at"] for x in conn.execute(
            "SELECT observed_at FROM knowledge_evidence WHERE knowledge_id=?", (r["id"],))]
        act = _activation(obs, r["pace_layer"])
        out.append(KnowledgeItem(
            id=r["id"], statement=r["statement"], epistemic_status=r["epistemic_status"],
            pace_layer=r["pace_layer"], confidence=r["confidence"],
            support=r["sup"], refute=r["ref"], independent=r["ind"],
            activation=None if act == float("-inf") else round(act, 3),
            entities=ents, created_at=r["created_at"],
            contested_at=r["contested_at"] if "contested_at" in r.keys() else None))
    conn.close()
    out.sort(key=lambda k: k.activation if k.activation is not None else -99, reverse=True)
    return out


class EvidenceDoc(BaseModel):
    doc_id: int | None
    title: str | None
    source_type: str | None
    stance: str
    independent: bool
    observed_at: str


@router.get("/items/{knowledge_id}/evidence", response_model=list[EvidenceDoc])
def knowledge_evidence(knowledge_id: int):
    """지식의 근거 사슬 — 어떤 문서가 지지/반박했나 (follow-up 동선)."""
    from database import get_connection
    conn = get_connection()
    rows = conn.execute("""
        SELECT ev.doc_id, ev.stance, ev.independent, ev.observed_at, rd.title, rd.source_type
        FROM knowledge_evidence ev LEFT JOIN raw_documents rd ON rd.id = ev.doc_id
        WHERE ev.knowledge_id=?
        ORDER BY ev.stance='refute' DESC, ev.independent DESC, ev.observed_at DESC""",
        (knowledge_id,)).fetchall()
    conn.close()
    return [EvidenceDoc(doc_id=r["doc_id"], title=r["title"], source_type=r["source_type"],
                        stance=r["stance"], independent=bool(r["independent"]),
                        observed_at=r["observed_at"]) for r in rows]


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
