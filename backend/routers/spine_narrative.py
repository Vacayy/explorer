"""주제 내러티브 API — theme_surge 고도화 (pipeline/narrative). 2단 게으른 패턴."""
import json

from fastapi import APIRouter
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/narrative", tags=["spine"])


class Narrative(BaseModel):
    status: str          # cached | fresh | empty | unavailable | failed | not_found
    title: str | None = None
    narrative: str | None = None
    created_at: str | None = None
    stale: bool = False
    category: str | None = None
    version: int | None = None
    narrative_id: int | None = None


class NarrativeItem(BaseModel):
    topic: str
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    share_pct: float | None = None
    share_delta_pp: float | None = None
    is_new: bool = False
    is_surging: bool = False
    created_at: str | None = None


class NarrativeList(BaseModel):
    items: list[NarrativeItem]


class CausalGraph(BaseModel):
    nodes: list[dict]    # [{name, type}]
    edges: list[dict]    # [{from, from_type, to, to_type, rel, mechanism, orientation, reference_period,
                          #   confidence, corroborated_by, contested}]


class RelatedNarrative(BaseModel):
    narrative_id: int
    topic: str
    title: str | None
    shared_nodes: list[str]


class Related(BaseModel):
    status: str          # ok | empty
    related: list[RelatedNarrative]


class GroundingItem(BaseModel):
    knowledge_id: int
    statement: str
    epistemic_status: str
    falsifiers: list[str]


class Grounding(BaseModel):
    status: str           # ok | empty
    grounding: list[GroundingItem]


class NarrativeVersion(BaseModel):
    id: int
    version: int
    title: str | None
    category: str | None
    created_at: str | None
    superseded_at: str | None


class ChainPath(BaseModel):
    nodes: list[dict]      # [{name, type}] root → … → 수혜 섹터
    edges: list[dict]      # [{from, to, rel, mechanism, orientation, reference_period, confidence}]
    confidence: float
    reaches_sector: bool


class Chain(BaseModel):
    status: str            # ok | empty
    paths: list[ChainPath]


class MerNarrative(BaseModel):
    status: str             # cached | fresh | empty | unavailable | failed
    narrative: str | None = None
    path: ChainPath | None = None
    stale: bool = False


class VersionDiff(BaseModel):
    status: str             # ok | not_found | no_prior_version
    prev_version_id: int | None = None
    added_nodes: list[str] = []
    removed_nodes: list[str] = []
    added_edges: list[dict] = []
    removed_edges: list[dict] = []
    summary: str | None = None


class MegaNarrative(BaseModel):
    id: int
    name: str            # 군집 이름 (LLM 명명, 예: 'AI 슈퍼사이클')
    title: str | None
    narrative: str | None
    members: list[str]   # 구성 sub-story 토픽들
    version: int
    created_at: str | None


@router.get("/mega", response_model=list[MegaNarrative])
def mega_list():
    """메가 내러티브(공유노드 군집의 상위 세계관 서사, D-031) — 살아있는 것만. LLM 없음."""
    from pipeline.mega_narrative import list_mega
    conn = get_connection()
    r = list_mega(conn)
    conn.close()
    return [MegaNarrative(**x) for x in r]


@router.get("/list", response_model=NarrativeList)
def list_narratives():
    """생성된 내러티브 모음 — 급증 주제 먼저, 나머지 최신순 (LLM 호출 없음)."""
    from pipeline.narrative import list_narratives as _list
    conn = get_connection()
    items = _list(conn)
    conn.close()
    return NarrativeList(items=items)


@router.get("", response_model=Narrative)
def get_narrative(topic: str):
    """캐시된 내러티브 + stale 플래그 — LLM 호출 없음."""
    from pipeline.narrative import cached_meta
    conn = get_connection()
    r = cached_meta(conn, topic)
    conn.close()
    return Narrative(**r)


@router.post("/compute", response_model=Narrative)
def compute(topic: str):
    """문서 집합이 바뀐 경우에만 opus 생성 — 멱등."""
    from pipeline.narrative import compute_narrative
    return Narrative(**compute_narrative(topic))


class ScenarioResult(BaseModel):
    status: str                       # ok | unavailable | error | none
    answer: str | None = None         # 파급 체인 마크다운
    beneficiaries: list[dict] = []    # 파급 논리로 지목된 수혜/피해 종목 (resolve+enrich, D-035)
    citations: list[dict] = []
    cached: bool = False              # 저장분 반환 여부 (D-038)
    created_at: str | None = None     # 저장분 생성 시각
    stale: bool = False               # 기반 내러티브가 갱신됨 → 재분석 권장


def _latest_narrative(conn, topic: str):
    return conn.execute(
        "SELECT title, version FROM narratives WHERE topic=? ORDER BY version DESC LIMIT 1",
        (topic,)).fetchone()


def _cached_scenario(conn, topic: str):
    return conn.execute(
        "SELECT event, answer, beneficiaries, citations, narrative_version, created_at "
        "FROM scenarios WHERE topic=?", (topic,)).fetchone()


@router.get("/scenario", response_model=ScenarioResult)
def scenario_cached(topic: str):
    """저장된 파급 시나리오 조회 — LLM 호출 없음. 없으면 status=none. (D-038 캐시)"""
    conn = get_connection()
    row = _cached_scenario(conn, topic)
    nar = _latest_narrative(conn, topic)
    conn.close()
    if not row:
        return ScenarioResult(status="none")
    stale = bool(nar and row["narrative_version"] is not None
                 and nar["version"] != row["narrative_version"])
    return ScenarioResult(
        status="ok", answer=row["answer"],
        beneficiaries=json.loads(row["beneficiaries"] or "[]"),
        citations=json.loads(row["citations"] or "[]"),
        cached=True, created_at=row["created_at"], stale=stale)


@router.post("/scenario/compute", response_model=ScenarioResult)
def scenario_compute(topic: str, refresh: bool = False):
    """내러티브 핵심 사건을 scenario 엔진으로 1·2·3차 파급 체인 전개 (opus, 온디맨드).
    '무엇이 일어났나(내러티브)'를 넘어 '왜·그래서 무엇'을 푸는 심층 인과 — 감시 조건까지.
    캐시(D-038): 기반 내러티브 버전이 그대로면 저장분 반환, refresh=1일 때만 opus 재생성."""
    from pipeline.scenario import build_scenario
    conn = get_connection()
    nar = _latest_narrative(conn, topic)
    version = nar["version"] if nar else None
    # 캐시 유효(내러티브 버전 동일) & refresh 아님 → 저장분 즉시 반환
    if not refresh:
        cur = _cached_scenario(conn, topic)
        if cur and cur["narrative_version"] == version:
            conn.close()
            return ScenarioResult(
                status="ok", answer=cur["answer"],
                beneficiaries=json.loads(cur["beneficiaries"] or "[]"),
                citations=json.loads(cur["citations"] or "[]"),
                cached=True, created_at=cur["created_at"])
    conn.close()

    event = f"{topic} — {nar['title']}" if nar and nar["title"] else topic
    try:
        r = build_scenario(event)
    except Exception:
        return ScenarioResult(status="error")
    if r.get("error"):
        return ScenarioResult(status="unavailable")

    beneficiaries = r.get("beneficiaries") or []
    citations = r.get("citations") or []
    conn = get_connection()
    conn.execute(
        "INSERT INTO scenarios (topic, event, answer, beneficiaries, citations, "
        "narrative_version, model, created_at) VALUES (?,?,?,?,?,?,?,datetime('now')) "
        "ON CONFLICT(topic) DO UPDATE SET event=excluded.event, answer=excluded.answer, "
        "beneficiaries=excluded.beneficiaries, citations=excluded.citations, "
        "narrative_version=excluded.narrative_version, model=excluded.model, "
        "created_at=excluded.created_at",
        (topic, event, r.get("answer"), json.dumps(beneficiaries, ensure_ascii=False),
         json.dumps(citations, ensure_ascii=False), version, r.get("model")))
    conn.commit()
    conn.close()
    return ScenarioResult(status="ok", answer=r.get("answer"),
                          beneficiaries=beneficiaries, citations=citations,
                          cached=False, created_at=None)


@router.get("/{narrative_id}/causal", response_model=CausalGraph)
def get_causal(narrative_id: int):
    """한 내러티브의 인과 서브그래프 (구조 뷰용) — LLM 없음."""
    from pipeline.narrative import causal_subgraph
    conn = get_connection()
    g = causal_subgraph(conn, narrative_id)
    conn.close()
    return CausalGraph(**g)


@router.get("/mer", response_model=MerNarrative)
def get_mer(topic: str):
    """캐시된 메르식 서사(순회 top-1 경로 정박) + stale — LLM 없음 (Phase 2 §2-2)."""
    from pipeline.narrative import cached_mer_meta
    conn = get_connection()
    r = cached_mer_meta(conn, topic)
    conn.close()
    return MerNarrative(**r)


@router.post("/mer/compute", response_model=MerNarrative)
def compute_mer(topic: str):
    """경로가 바뀐 경우에만 opus 생성 — 멱등."""
    from pipeline.narrative import compute_mer_narrative
    return MerNarrative(**compute_mer_narrative(topic))


@router.get("/{narrative_id}/chain", response_model=Chain)
def get_chain(narrative_id: int):
    """근본 원인↔수혜 섹터 순회 경로 (Phase 2 §2-1) — 전역 인과 그래프 순회, LLM 없음."""
    from pipeline.narrative_graph import narrative_chain
    conn = get_connection()
    r = narrative_chain(conn, narrative_id)
    conn.close()
    return Chain(**r)


@router.get("/{narrative_id}/grounding", response_model=Grounding)
def get_grounding(narrative_id: int):
    """이 내러티브가 딛고 선 승격된 지식 + 흔들릴 조건(미발화 반증), LLM 없음 (Phase 2 §2-5)."""
    from pipeline.narrative import narrative_grounding
    conn = get_connection()
    r = narrative_grounding(conn, narrative_id)
    conn.close()
    return Grounding(**r)


@router.get("/{narrative_id}/related", response_model=Related)
def get_related(narrative_id: int):
    """인과 노드를 공유하는 다른 내러티브(주제별 최신 버전) — 공유 수 랭킹, LLM 없음 (Phase 2 §2-4)."""
    from pipeline.narrative import related_narratives
    conn = get_connection()
    r = related_narratives(conn, narrative_id)
    conn.close()
    return Related(**r)


@router.get("/{narrative_id}/diff", response_model=VersionDiff)
def get_diff(narrative_id: int):
    """직전 버전 대비 인과 그래프 변화 — added/removed 노드·엣지(LLM 없음) + 게으른 haiku
    한 줄 요약(캐시) (Phase 2 §2-3)."""
    from pipeline.narrative import narrative_diff
    conn = get_connection()
    r = narrative_diff(conn, narrative_id)
    conn.close()
    return VersionDiff(**r)


@router.get("/versions", response_model=list[NarrativeVersion])
def versions(topic: str):
    """주제의 내러티브 버전 목록 (드리프트 추적 기초) — 최신순."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, version, title, category, created_at, superseded_at FROM narratives "
        "WHERE topic=? ORDER BY version DESC", (topic,)).fetchall()
    conn.close()
    return [NarrativeVersion(**dict(r)) for r in rows]


@router.get("/version", response_model=Narrative)
def get_version(id: int):
    """특정 버전 본문 by id — 히스토리 타임라인 도트 클릭 시 열람 (D-060). LLM 없음.
    supersede가 이전 버전 body를 지우지 않으므로 모든 버전 본문이 보존된다."""
    conn = get_connection()
    r = conn.execute(
        "SELECT id, title, body, category, version, created_at FROM narratives WHERE id=?",
        (id,)).fetchone()
    conn.close()
    if not r:
        return Narrative(status="not_found")
    return Narrative(status="cached", title=r["title"], narrative=r["body"],
                     created_at=r["created_at"], category=r["category"],
                     version=r["version"], narrative_id=r["id"])
