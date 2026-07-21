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
                         #   reference_period, geo_scope, confidence, corroborated_by, contested,
                         #   feedback_note, promoted_knowledge_id}]  feedback_note=both_temporal 해소 근거(D-029),
                         #   geo_scope=인과 주장의 장소 스코프(D-034)
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


class NodeContext(BaseModel):
    node: dict | None = None            # {id, name, type, in_degree, out_degree, ...}
    causes: list[dict] = []             # 이 노드로 들어오는 인과 엣지 (worldview edge 형태)
    effects: list[dict] = []            # 이 노드에서 나가는 인과 엣지


@router.get("/node/{entity_id}/context", response_model=NodeContext)
def get_node_context(entity_id: int):
    """이슈(노드) 디테일용 — 노드 + 인과 논리(원인·결과 엣지, mechanism·geo 포함). LLM 없음.
    full_causal_graph 재사용으로 corroborated_by·contested·feedback_note 등 필드 일관."""
    from pipeline.narrative_graph import full_causal_graph
    conn = get_connection()
    g = full_causal_graph(conn)
    conn.close()
    node = next((n for n in g["nodes"] if n["id"] == entity_id), None)
    causes = [e for e in g["edges"] if e.get("to_id") == entity_id]
    effects = [e for e in g["edges"] if e.get("from_id") == entity_id]
    return NodeContext(node=node, causes=causes, effects=effects)


class ActivityBeneficiary(BaseModel):
    stock_code: str
    name: str
    rs_short: int | None = None


class GraphActivityNode(BaseModel):
    id: int
    name: str
    type: str
    is_new: bool
    new_edges: int
    beneficiaries: list[ActivityBeneficiary] = []


@router.get("/activity", response_model=list[GraphActivityNode])
def get_graph_activity(days: int = 7, limit: int = 12):
    """인과 그래프 델타 — 최근 새 엣지가 붙은 노드(신규/갱신) + 섹터/테마면 수혜 종목 (D-035). LLM 없음."""
    from pipeline.beneficiary import graph_activity
    conn = get_connection()
    r = graph_activity(conn, days=days, limit=limit)
    conn.close()
    return [GraphActivityNode(**x) for x in r]


# 수혜 섹터 → 종목 후보 스크린 (action_thesis Phase 1) — 세계관/인과 계열이라 여기 둔다.
beneficiary_router = APIRouter(prefix="/api/spine/beneficiary", tags=["spine"])


class BeneficiaryCandidate(BaseModel):
    stock_code: str
    entity_id: int
    name: str
    rs_short: int
    rs_prev: int | None = None
    per: float | None = None
    pbr: float | None = None
    market_cap: int | None = None
    pos_52w: int | None = None
    co_mentions: int
    relevance: float | None = None


@beneficiary_router.get("/screen", response_model=list[BeneficiaryCandidate])
def screen_beneficiary_candidates(sector: str, limit: int = 12):
    """수혜 섹터/테마 → 종목 후보 (문서 공동언급 + RS·밸류·시총·52주 위치). LLM 없음."""
    from pipeline.beneficiary import screen_beneficiaries
    conn = get_connection()
    r = screen_beneficiaries(conn, sector, limit)
    conn.close()
    return r


# 업사이드 모델 — 이벤트 → 종목 조건부 업사이드/하방 정량 (action_thesis Phase 2, 온디맨드 opus)
class UpsideAnchor(BaseModel):
    price: float | None = None
    eps: float | None = None
    per: float | None = None
    revenue: int | None = None
    net_margin: float | None = None


class UpsideScenario(BaseModel):
    name: str
    prob: float | None = None
    assumptions: list[str] = []
    revenue_delta_pct: float | None = None
    margin: float | None = None
    eps_new: float | None = None
    multiple: float | None = None
    fair_price: float | None = None
    upside_pct: float | None = None


class UpsideDownside(BaseModel):
    floor_price: float | None = None
    downside_pct: float | None = None
    basis: str | None = None


class UpsideModel(BaseModel):
    status: str
    stock: str | None = None
    stock_code: str | None = None
    anchor: UpsideAnchor | None = None
    method: str | None = None
    scenarios: list[UpsideScenario] = []
    downside: UpsideDownside | None = None
    invalidation: list[str] = []
    summary: str | None = None


@beneficiary_router.post("/upside", response_model=UpsideModel)
def upside(stock: str, event: str):
    """이벤트 → 종목(=stock 종목코드) 조건부 업사이드/하방 모델링 (opus, models 적재)."""
    from pipeline.upside_model import build_upside_model
    conn = get_connection()
    try:
        return build_upside_model(conn, stock, event)
    except Exception:
        return {"status": "error"}
    finally:
        conn.close()
