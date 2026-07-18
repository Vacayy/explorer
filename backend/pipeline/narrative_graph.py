"""인과 그래프 순회 — 앞의 끝(근본 원인)·뒤의 끝(수혜 섹터) + 경로 구성 (Phase 2 §2-1, D-023).

방향 규약(narrative.py 프롬프트와 동일):
- CAUSES: src=원인, dst=결과 — 흐름은 저장 방향과 같다(src→dst).
- BENEFITS_FROM: src=수혜 섹터, dst=체인 말단 동인 — 흐름은 저장 방향의 반대(dst→src,
  "동인이 섹터에 수혜를 준다"). 하류 순회는 이 비대칭을 반영해 항상 인과 흐름 방향으로 걷는다.

상류(근본 원인)는 CAUSES만 쓴다(스펙 2-1). 하류(수혜)는 CAUSES∪BENEFITS_FROM을 쓰고
종착은 type='sector' 노드. 정지 규칙:
- 상류: 들어오는 CAUSES 엣지가 없는 노드(위상적 소스) 또는 깊이 한도.
- 하류: sector 노드 도달 또는 더 갈 곳 없음/깊이 한도.
"""
from database import get_connection
from pipeline.narrative import causal_subgraph

MAX_DEPTH = 6
MAX_BRANCH = 4     # 노드당 다음 후보 상한 — 그래프 폭발 방지
MAX_PATHS_PER_ANCHOR = 5
TOP_K = 3


def _entity_id(conn, name: str) -> int | None:
    row = conn.execute("SELECT id FROM entities WHERE name=? LIMIT 1", (name,)).fetchone()
    return row["id"] if row else None


def _upstream_step(conn, node_id: int) -> list[dict]:
    """node_id를 결과(dst)로 갖는 CAUSES 엣지 — 원인(src) 후보."""
    return [dict(r) for r in conn.execute(
        "SELECT er.src_id nid, er.confidence, er.mechanism, er.time_orientation orientation, "
        "er.reference_period, e.name, e.type, 'CAUSES' rel "
        "FROM entity_relations er JOIN entities e ON e.id = er.src_id "
        "WHERE er.dst_id=? AND er.rel_type='CAUSES' "
        "ORDER BY er.confidence DESC LIMIT ?", (node_id, MAX_BRANCH)).fetchall()]


def _downstream_step(conn, node_id: int) -> list[dict]:
    """node_id 이후 하류 — CAUSES(src=node_id→dst) ∪ BENEFITS_FROM(dst=node_id→src, 수혜 방향)."""
    return [dict(r) for r in conn.execute(
        "SELECT er.dst_id nid, er.confidence, er.mechanism, er.time_orientation orientation, "
        "er.reference_period, e.name, e.type, 'CAUSES' rel "
        "FROM entity_relations er JOIN entities e ON e.id = er.dst_id "
        "WHERE er.src_id=? AND er.rel_type='CAUSES' "
        "UNION ALL "
        "SELECT er.src_id nid, er.confidence, er.mechanism, er.time_orientation orientation, "
        "er.reference_period, e.name, e.type, 'BENEFITS_FROM' rel "
        "FROM entity_relations er JOIN entities e ON e.id = er.src_id "
        "WHERE er.dst_id=? AND er.rel_type='BENEFITS_FROM' "
        "ORDER BY confidence DESC LIMIT ?", (node_id, node_id, MAX_BRANCH)).fetchall()]


def _walk_upstream(conn, start_id: int, max_depth: int = MAX_DEPTH) -> list[list[dict]]:
    """start_id에서 거슬러 올라간 경로들 — 각 경로는 hop 리스트, anchor에서 먼 순서(root가 끝).
    빈 리스트는 'start_id 자신이 이미 근본 원인(위상적 소스)'을 뜻한다."""
    results: list[list[dict]] = []

    def dfs(node_id: int, path: list[dict], visited: set[int]):
        if len(results) >= MAX_PATHS_PER_ANCHOR:
            return
        if len(path) >= max_depth:
            results.append(path)
            return
        steps = [s for s in _upstream_step(conn, node_id) if s["nid"] not in visited]
        if not steps:
            results.append(path)
            return
        for s in steps:
            dfs(s["nid"], path + [s], visited | {s["nid"]})

    dfs(start_id, [], {start_id})
    return results


def _walk_downstream(conn, start_id: int, start_type: str | None,
                      max_depth: int = MAX_DEPTH) -> list[list[dict]]:
    """start_id에서 하류로 걸은 경로들 — anchor에서 가까운 순서(sector 도달 시 끝).
    빈 리스트는 'start_id 자신이 이미 sector(종착)'이거나 더 갈 곳이 없음을 뜻한다."""
    results: list[list[dict]] = []
    if start_type == "sector":
        return [[]]

    def dfs(node_id: int, path: list[dict], visited: set[int]):
        if len(results) >= MAX_PATHS_PER_ANCHOR:
            return
        if len(path) >= max_depth:
            results.append(path)
            return
        steps = [s for s in _downstream_step(conn, node_id) if s["nid"] not in visited]
        if not steps:
            results.append(path)
            return
        for s in steps:
            if s["type"] == "sector":
                results.append(path + [s])
                continue
            dfs(s["nid"], path + [s], visited | {s["nid"]})

    dfs(start_id, [], {start_id})
    return results


def _path_confidence(hops: list[dict]) -> float:
    if not hops:
        return 1.0
    conf = 1.0
    for h in hops:
        conf *= h.get("confidence") if h.get("confidence") is not None else 0.5
    return round(conf, 4)


def _materialize(conn, anchor_id: int, anchor_name: str, anchor_type: str,
                  up_hops: list[dict], down_hops: list[dict]) -> dict:
    """up_hops(anchor→근본, 먼 순)+anchor+down_hops(anchor→수혜, 가까운 순)를
    근본→…→anchor→…→수혜 순서의 nodes/edges로 조립."""
    nodes = [{"name": h["name"], "type": h["type"]} for h in reversed(up_hops)]
    nodes.append({"name": anchor_name, "type": anchor_type})
    nodes.extend({"name": h["name"], "type": h["type"]} for h in down_hops)

    edges = []
    # 상류 구간: hops는 [가장 가까운 원인, ..., 가장 먼 원인] — 역순으로 걸으면 root→anchor 방향.
    chain = list(reversed(up_hops)) + down_hops
    for i, h in enumerate(chain):
        a = nodes[i]["name"]
        b = nodes[i + 1]["name"]
        edges.append({
            "from": a, "to": b, "rel": h["rel"], "mechanism": h.get("mechanism"),
            "orientation": h.get("orientation"), "reference_period": h.get("reference_period"),
            "confidence": h.get("confidence"),
        })
    return {
        "nodes": nodes, "edges": edges,
        "confidence": round(_path_confidence(up_hops) * _path_confidence(down_hops), 4),
        "reaches_sector": (bool(down_hops) and down_hops[-1]["type"] == "sector")
        or anchor_type == "sector",
    }


def narrative_chain(conn, narrative_id: int, top_k: int = TOP_K) -> dict:
    """내러티브의 인과 서브그래프 노드들을 앵커로, 전역 그래프에서 근본 원인↔수혜 섹터까지
    순회해 root→…→수혜 경로 top_k개를 confidence 곱 랭킹으로 반환."""
    sub = causal_subgraph(conn, narrative_id)
    anchors = []
    for n in sub["nodes"]:
        eid = _entity_id(conn, n["name"])
        if eid is not None:
            anchors.append((eid, n["name"], n["type"]))
    if not anchors:
        return {"status": "empty", "paths": []}

    candidates = []
    seen_seq = set()
    for eid, name, etype in anchors:
        up_paths = _walk_upstream(conn, eid)
        down_paths = _walk_downstream(conn, eid, etype)
        for up in up_paths:
            for down in down_paths:
                path = _materialize(conn, eid, name, etype, up, down)
                seq = tuple(nd["name"] for nd in path["nodes"])
                if seq in seen_seq or len(seq) < 2:
                    continue
                seen_seq.add(seq)
                candidates.append(path)

    candidates.sort(key=lambda p: -p["confidence"])
    return {"status": "ok" if candidates else "empty", "paths": candidates[:top_k]}
