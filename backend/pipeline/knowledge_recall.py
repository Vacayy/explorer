"""지식 소환 (K1) — 승격된 지식을 소비 지점(RAG·브리프)에 공급.

설계 (docs/specs/knowledge-hierarchy-design.md §소비 지점):
- activation은 저장하지 않고 조회 시 계산 (A-2) — 증거 타임스탬프 × 층별 감쇠율
- 랭킹: relevance × f(activation) × g(epistemic — corroborated > observed > contested)
- pace layer 라벨을 항상 동반한다 — "지금 시끄러운 것"(event/flow)과
  "구조적인 것"(structure/regime)을 소비자가 섞지 않게 (A-6 가용성 휴리스틱 보정)
"""
import math

from pipeline.consolidation import _cosine, _embed_statements, activation

EPISTEMIC_W = {"corroborated": 1.0, "observed": 0.7, "hypothesis": 0.5, "contested": 0.35}
MIN_QUERY_SIM = 0.45   # 질문-주장 최소 유사도 (multilingual-MiniLM cosine)

LAYER_KO = {"event": "사건", "flow": "흐름", "cycle": "사이클", "structure": "구조", "regime": "체제"}


def _f_activation(act: float) -> float:
    """ln 스케일 activation → (0,1) 가중 — 죽은 지식은 뒤로, 삭제는 아님."""
    return 1 / (1 + math.exp(-act)) if act != float("-inf") else 0.05


def _load_active(conn, entity_id: int | None = None) -> list[dict]:
    """active 지식 + 증거 집계 (독립 수·반박 수·observed_at들) → activation 계산."""
    if entity_id is not None:
        rows = conn.execute("""
            SELECT k.id, k.statement, k.epistemic_status, k.pace_layer
            FROM knowledge k JOIN knowledge_entities ke ON ke.knowledge_id = k.id
            WHERE ke.entity_id=? AND k.review_status='active' AND k.valid_to IS NULL
        """, (entity_id,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT id, statement, epistemic_status, pace_layer FROM knowledge
            WHERE review_status='active' AND valid_to IS NULL""").fetchall()
    out = []
    for r in rows:
        ev = conn.execute("""
            SELECT stance, independent, observed_at FROM knowledge_evidence
            WHERE knowledge_id=?""", (r["id"],)).fetchall()
        item = dict(r)
        item["independent_n"] = sum(1 for e in ev if e["stance"] == "support" and e["independent"])
        item["refute_n"] = sum(1 for e in ev if e["stance"] == "refute")
        item["activation"] = activation([e["observed_at"] for e in ev], r["pace_layer"])
        out.append(item)
    return out


def _score(item: dict, relevance: float = 1.0) -> float:
    return relevance * _f_activation(item["activation"]) \
        * EPISTEMIC_W.get(item["epistemic_status"], 0.5)


NEIGHBOR_MIN_DOCS = 3     # 1-hop 이웃 인정 최소 공출현 문서 수
NEIGHBOR_DISCOUNT = 0.6   # 이웃 경유 지식의 relevance 할인

def recall_for_entity(conn, entity_id: int, limit: int = 5) -> list[dict]:
    """브리프용 — 직접 연결 지식 + 1-hop 그래프 확산 (HippoRAG 최소 번안).

    지식은 대개 섹터·테마 엔티티에 붙는다 — 종목 직접 링크만 보면 소환이 빈약.
    문서 공출현이 잦은 이웃 엔티티의 지식을 할인 가중으로 함께 소환한다.
    """
    direct = _load_active(conn, entity_id)
    seen = {k["id"] for k in direct}
    scored = [(_score(k), k) for k in direct]

    neighbors = [r["entity_id"] for r in conn.execute("""
        SELECT el2.entity_id, COUNT(DISTINCT el1.doc_id) n
        FROM entity_links el1 JOIN entity_links el2 ON el1.doc_id = el2.doc_id
        WHERE el1.entity_id=? AND el2.entity_id != el1.entity_id
        GROUP BY el2.entity_id HAVING n >= ? ORDER BY n DESC LIMIT 20
    """, (entity_id, NEIGHBOR_MIN_DOCS))]
    for nid in neighbors:
        for k in _load_active(conn, nid):
            if k["id"] in seen:
                continue
            seen.add(k["id"])
            scored.append((_score(k, NEIGHBOR_DISCOUNT), k))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [k for _, k in scored[:limit]]


def recall_for_query(conn, query: str, limit: int = 4) -> list[dict]:
    """RAG용 — 질문과 의미 유사한 지식, relevance×activation×epistemic 순."""
    items = _load_active(conn)
    if not items:
        return []
    embs = _embed_statements([query] + [i["statement"] for i in items])
    q = embs[0]
    scored = []
    for item, e in zip(items, embs[1:]):
        sim = _cosine(q, e)
        if sim < MIN_QUERY_SIM:
            continue
        item["relevance"] = sim
        scored.append((_score(item, sim), item))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [item for _, item in scored[:limit]]


def knowledge_block(items: list[dict], header: str) -> str:
    """소비 지점 공통 프롬프트 블록 — 층위·지위·관측 수를 라벨로 명시."""
    if not items:
        return ""
    lines = []
    for i, k in enumerate(items, 1):
        tags = f"{k['epistemic_status']} · {LAYER_KO.get(k['pace_layer'], k['pace_layer'])}층 · 독립 관측 {k['independent_n']}"
        if k["refute_n"]:
            tags += f" · 반박 {k['refute_n']}"
        lines.append(f"K{i}. ({tags}) {k['statement']}")
    return f"\n\n[{header}]\n" + "\n".join(lines)
