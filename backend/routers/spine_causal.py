"""전역 인과 그래프 API — 세계관 뷰 (narrative_id 스코프 없는 전체 그래프, 그래프 시각화 기획서)."""
from fastapi import APIRouter
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/causal", tags=["spine"])


class WorldviewNode(BaseModel):
    id: int
    name: str
    type: str
    in_degree: int
    out_degree: int
    cluster_id: int
    in_flywheel: bool = False   # 자기강화 루프(SCC) 소속 (D-027 반사성)


class Worldview(BaseModel):
    nodes: list[WorldviewNode]
    edges: list[dict]   # [{from, from_id, from_type, to, to_id, to_type, rel, mechanism, orientation,
                         #   reference_period, confidence, corroborated_by, contested, promoted_knowledge_id}]
                         # from이 파이썬 예약어라 CausalGraph(spine_narrative.py)와 동일하게 dict로 통과


class NodeNarrative(BaseModel):
    id: int
    topic: str
    title: str | None


@router.get("/worldview", response_model=Worldview)
def get_worldview(category: str | None = None):
    """전체 인과 그래프 — 노드·엣지 + 연결요소(cluster_id). LLM 없음."""
    from pipeline.narrative_graph import full_causal_graph
    conn = get_connection()
    g = full_causal_graph(conn, category=category)
    conn.close()
    return Worldview(nodes=g["nodes"], edges=g["edges"])


@router.get("/node/{entity_id}/narratives", response_model=list[NodeNarrative])
def get_node_narratives(entity_id: int):
    """이 노드가 등장하는 내러티브 — 디테일 패널용. LLM 없음."""
    from pipeline.narrative_graph import nodes_in_narratives
    conn = get_connection()
    r = nodes_in_narratives(conn, entity_id)
    conn.close()
    return [NodeNarrative(**x) for x in r]
