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


def recall_for_query(conn, query: str, limit: int = 4, min_sim: float = MIN_QUERY_SIM) -> list[dict]:
    """RAG용 — 질문과 의미 유사한 지식, relevance×activation×epistemic 순. min_sim으로 문턱 조절(도구 폴백용)."""
    items = _load_active(conn)
    if not items:
        return []
    embs = _embed_statements([query] + [i["statement"] for i in items])
    q = embs[0]
    scored = []
    for item, e in zip(items, embs[1:]):
        sim = _cosine(q, e)
        if sim < min_sim:
            continue
        item["relevance"] = sim
        scored.append((_score(item, sim), item))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [item for _, item in scored[:limit]]


# 지식의 확실성을 '자연어 힌트'로만 — 확립/관측은 전제로 취급(무표기), 약한 것만 표시.
# 'corroborated'·'K1' 같은 내부 라벨이 사용자 출력에 새지 않게 (원칙: 내부 코드 비노출)
_EPI_HINT = {"hypothesis": " (아직 가설)", "contested": " (이견 있음)"}


def knowledge_block(items: list[dict], header: str) -> str:
    """소비 지점 공통 프롬프트 블록 — 판단의 배경 전제.

    번호(K1…)·영어 지위(corroborated)·관측 수 같은 내부 라벨은 넣지 않는다.
    모델이 그대로 인용하면 사용자에게 정체불명 코드로 노출되기 때문 (자연어로만).
    """
    if not items:
        return ""
    lines = [f"- {k['statement']}{_EPI_HINT.get(k['epistemic_status'], '')}" for k in items]
    return (
        f"\n\n[{header}]\n" + "\n".join(lines)
        + "\n(위는 판단의 배경 전제다. 답변에 'K1'·'corroborated' 같은 내부 라벨이나 "
        "'근거: …' 식 출처 표기를 노출하지 말 것 — 필요하면 자연스러운 한국어 서술에 녹여라.)"
    )
