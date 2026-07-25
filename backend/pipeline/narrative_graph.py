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
import json

from database import get_connection
from pipeline.narrative import causal_subgraph

MAX_DEPTH = 6
MAX_BRANCH = 4     # 노드당 다음 후보 상한 — 그래프 폭발 방지
MAX_PATHS_PER_ANCHOR = 5
TOP_K = 3


def _entity_id(conn, name: str) -> int | None:
    row = conn.execute("SELECT id FROM entities WHERE name=? LIMIT 1", (name,)).fetchone()
    return row["id"] if row else None


ROOT_LAYERS = ("regime", "structure")   # 이 층 노드 도달 = 근본 원인 (D-030 루트 정지 정밀화)


def _upstream_step(conn, node_id: int) -> list[dict]:
    """node_id를 결과(dst)로 갖는 CAUSES 엣지 — 원인(src) 후보 (+pace_layer, 루트 정지용)."""
    out = []
    for r in conn.execute(
        "SELECT er.id eid, er.src_id nid, er.confidence, "
        "er.effect_direction, er.effect_strength, er.mechanism, "
        "er.time_orientation orientation, "
        "er.reference_period, e.name, e.type, e.meta_json, 'CAUSES' rel "
        "FROM entity_relations er JOIN entities e ON e.id = er.src_id "
        "WHERE er.dst_id=? AND er.rel_type='CAUSES' "
            "ORDER BY er.confidence DESC LIMIT ?", (node_id, MAX_BRANCH)).fetchall():
        d = dict(r)
        meta = d.pop("meta_json", None)
        try:
            d["pace_layer"] = (json.loads(meta) or {}).get("pace_layer") if meta else None
        except (ValueError, TypeError):
            d["pace_layer"] = None
        out.append(d)
    return out


def _downstream_step(conn, node_id: int) -> list[dict]:
    """node_id 이후 하류 — CAUSES(src=node_id→dst) ∪ BENEFITS_FROM(dst=node_id→src, 수혜 방향)."""
    return [dict(r) for r in conn.execute(
        "SELECT er.id eid, er.dst_id nid, er.confidence, "
        "er.effect_direction, er.effect_strength, er.mechanism, "
        "er.time_orientation orientation, "
        "er.reference_period, e.name, e.type, 'CAUSES' rel "
        "FROM entity_relations er JOIN entities e ON e.id = er.dst_id "
        "WHERE er.src_id=? AND er.rel_type='CAUSES' "
        "UNION ALL "
        "SELECT er.id eid, er.src_id nid, er.confidence, "
        "er.effect_direction, er.effect_strength, er.mechanism, "
        "er.time_orientation orientation, "
        "er.reference_period, e.name, e.type, 'BENEFITS_FROM' rel "
        "FROM entity_relations er JOIN entities e ON e.id = er.src_id "
        "WHERE er.dst_id=? AND er.rel_type='BENEFITS_FROM' "
        "ORDER BY confidence DESC LIMIT ?", (node_id, node_id, MAX_BRANCH)).fetchall()]


def _walk_upstream(conn, start_id: int, max_depth: int = MAX_DEPTH) -> list[list[dict]]:
    """start_id에서 거슬러 올라간 경로들 — 각 경로는 hop 리스트, anchor에서 먼 순서(root가 끝).
    빈 리스트는 'start_id 자신이 이미 근본 원인(위상적 소스)'을 뜻한다.

    방문집합 = 엣지 id (D-027 반사성): 노드 재방문은 허용하되 같은 엣지 재사용만 금지 —
    시점이 다른 두 엣지로 펴진 피드백 나선(A→B(t1), B→A(t2))을 걸을 수 있게. 무한루프는
    엣지 유한성 + max_depth가 이중으로 막는다.

    루트 정지(D-030): regime/structure 층 노드에 닿으면 거기가 근본 원인 — 더 거슬러
    올라가지 않는다 (무한 후퇴 방지의 정밀판, layer 미태깅 노드는 기존 위상 규칙대로)."""
    results: list[list[dict]] = []

    def dfs(node_id: int, path: list[dict], used_edges: set[int]):
        if len(results) >= MAX_PATHS_PER_ANCHOR:
            return
        if len(path) >= max_depth:
            results.append(path)
            return
        steps = [s for s in _upstream_step(conn, node_id) if s["eid"] not in used_edges]
        if not steps:
            results.append(path)
            return
        for s in steps:
            if s.get("pace_layer") in ROOT_LAYERS:
                results.append(path + [s])   # 구조적 뿌리 도달 — 정지
                continue
            dfs(s["nid"], path + [s], used_edges | {s["eid"]})

    dfs(start_id, [], set())
    return results


def _walk_downstream(conn, start_id: int, start_type: str | None,
                      max_depth: int = MAX_DEPTH) -> list[list[dict]]:
    """start_id에서 하류로 걸은 경로들 — anchor에서 가까운 순서(sector 도달 시 끝).
    빈 리스트는 'start_id 자신이 이미 sector(종착)'이거나 더 갈 곳이 없음을 뜻한다.
    방문집합 = 엣지 id (D-027 반사성 — _walk_upstream과 동일 규칙)."""
    results: list[list[dict]] = []
    if start_type == "sector":
        return [[]]

    def dfs(node_id: int, path: list[dict], used_edges: set[int]):
        if len(results) >= MAX_PATHS_PER_ANCHOR:
            return
        if len(path) >= max_depth:
            results.append(path)
            return
        steps = [s for s in _downstream_step(conn, node_id) if s["eid"] not in used_edges]
        if not steps:
            results.append(path)
            return
        for s in steps:
            if s["type"] == "sector":
                results.append(path + [s])
                continue
            dfs(s["nid"], path + [s], used_edges | {s["eid"]})

    dfs(start_id, [], set())
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
            "effect_direction": h.get("effect_direction"), "effect_strength": h.get("effect_strength"),
        })
    return {
        "nodes": nodes, "edges": edges,
        "path_confidence": round(_path_confidence(up_hops) * _path_confidence(down_hops), 4),
        "reaches_sector": (bool(down_hops) and down_hops[-1]["type"] == "sector")
        or anchor_type == "sector",
    }


def narrative_chain(conn, narrative_id: int, top_k: int = TOP_K) -> dict:
    """내러티브의 인과 서브그래프 노드들을 앵커로, 전역 그래프에서 근본 원인↔수혜 섹터까지
    순회해 root→…→수혜 경로 top_k개를 path_confidence(경로 신뢰도=엣지 confidence 곱) 랭킹으로 반환."""
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

    candidates.sort(key=lambda p: -p["path_confidence"])
    return {"status": "ok" if candidates else "empty", "paths": candidates[:top_k]}


def full_causal_graph(conn, category: str | None = None) -> dict:
    """전역 인과 그래프 — narrative_id 스코프 없이 전체 CAUSES/BENEFITS_FROM 엣지·노드
    (세계관 뷰, 그래프 시각화 기획서 §2). 엣지마다 교차검증 정보(causal_subgraph와 동일 계산)를
    얹고, 무향 기준 연결요소(cluster_id, union-find, LLM 0)로 "같은 세계관" 묶음을 매긴다.
    category 필터는 이 엣지를 주장한 내러티브(narrative_edge_evidence 경유, 다대다) 중 하나라도
    해당 도메인 렌즈를 걸치면 포함 — 현재 태그 하나만 보는 것보다 정확하다."""
    edges = conn.execute("""
        SELECT er.id, er.rel_type, er.mechanism, er.reference_period, er.time_orientation,
               er.confidence, er.effect_direction, er.effect_strength,
               er.promoted_knowledge_id, er.feedback_note, er.geo_scope,
               s.id sid, s.name sname, s.type stype, s.meta_json smeta,
               d.id did, d.name dname, d.type dtype, d.meta_json dmeta
        FROM entity_relations er
        JOIN entities s ON s.id=er.src_id JOIN entities d ON d.id=er.dst_id
        WHERE er.rel_type IN ('CAUSES','BENEFITS_FROM')
        ORDER BY er.id""").fetchall()

    if category:
        keep = []
        for e in edges:
            cats = conn.execute("""
                SELECT DISTINCT n.category FROM narrative_edge_evidence nee
                JOIN narratives n ON n.id = nee.narrative_id
                WHERE nee.entity_relation_id = ?""", (e["id"],)).fetchall()
            if any(category in (c["category"] or "").split(",") for c in cats):
                keep.append(e)
        edges = keep

    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    def _layer(meta: str | None) -> str | None:
        try:
            return (json.loads(meta) or {}).get("pace_layer") if meta else None
        except (ValueError, TypeError):
            return None

    nodes: dict[int, dict] = {}
    out_edges = []
    for e in edges:
        nodes.setdefault(e["sid"], {"id": e["sid"], "name": e["sname"], "type": e["stype"],
                                     "pace_layer": _layer(e["smeta"]),
                                     "in_degree": 0, "out_degree": 0})
        nodes.setdefault(e["did"], {"id": e["did"], "name": e["dname"], "type": e["dtype"],
                                     "pace_layer": _layer(e["dmeta"]),
                                     "in_degree": 0, "out_degree": 0})
        union(e["sid"], e["did"])
        n_narratives = conn.execute(
            "SELECT COUNT(DISTINCT narrative_id) c FROM narrative_edge_evidence WHERE entity_relation_id=?",
            (e["id"],)).fetchone()["c"]
        # feedback_note가 있으면 opus가 '상충 아닌 시점 다른 피드백 나선'으로 해소한 것 → contested 제외(D-029)
        contested = e["rel_type"] == "CAUSES" and not e["feedback_note"] and conn.execute(
            "SELECT 1 FROM entity_relations er2 JOIN entities s2 ON s2.id=er2.src_id "
            "JOIN entities d2 ON d2.id=er2.dst_id WHERE er2.rel_type='CAUSES' AND s2.name=? AND d2.name=?",
            (e["dname"], e["sname"])).fetchone() is not None
        nodes[e["sid"]]["out_degree"] += 1
        nodes[e["did"]]["in_degree"] += 1
        out_edges.append({
            "from": e["sname"], "from_id": e["sid"], "from_type": e["stype"],
            "to": e["dname"], "to_id": e["did"], "to_type": e["dtype"],
            "rel": e["rel_type"], "mechanism": e["mechanism"], "orientation": e["time_orientation"],
            "reference_period": e["reference_period"], "confidence": e["confidence"],
            "effect_direction": e["effect_direction"], "effect_strength": e["effect_strength"],
            "corroborated_by": n_narratives, "contested": contested,
            "feedback_note": e["feedback_note"], "geo_scope": e["geo_scope"],
            "promoted_knowledge_id": e["promoted_knowledge_id"],
        })

    for nid, node in nodes.items():
        node["cluster_id"] = find(nid)

    _mark_flywheels(nodes, out_edges)
    return {"nodes": list(nodes.values()), "edges": out_edges}


def _mark_flywheels(nodes: dict[int, dict], edges: list[dict]) -> None:
    """자기강화 루프(플라이휠) 감지 (D-027 반사성) — CAUSES 엣지의 방향 그래프에서
    크기 2+ 강연결요소(SCC, Tarjan 반복형)에 속한 노드·엣지에 flywheel 플래그.
    시점이 다른 두 엣지로 펴진 피드백(A→B(t1), B→A(t2))이 노드 공간에선 SCC로 나타난다."""
    adj: dict[int, list[int]] = {}
    for e in edges:
        if e["rel"] == "CAUSES":
            adj.setdefault(e["from_id"], []).append(e["to_id"])

    index: dict[int, int] = {}
    lowlink: dict[int, int] = {}
    on_stack: set[int] = set()
    stack: list[int] = []
    scc_of: dict[int, int] = {}
    counter = [0]
    scc_id = [0]

    def strongconnect(root: int):
        work = [(root, 0)]
        while work:
            v, pi = work[-1]
            if pi == 0:
                index[v] = lowlink[v] = counter[0]
                counter[0] += 1
                stack.append(v)
                on_stack.add(v)
            recurse = False
            neighbors = adj.get(v, [])
            for i in range(pi, len(neighbors)):
                w = neighbors[i]
                if w not in index:
                    work[-1] = (v, i + 1)
                    work.append((w, 0))
                    recurse = True
                    break
                if w in on_stack:
                    lowlink[v] = min(lowlink[v], index[w])
            if recurse:
                continue
            if lowlink[v] == index[v]:
                members = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    members.append(w)
                    if w == v:
                        break
                if len(members) >= 2:
                    for m in members:
                        scc_of[m] = scc_id[0]
                    scc_id[0] += 1
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[v])

    for v in adj:
        if v not in index:
            strongconnect(v)

    for nid, node in nodes.items():
        node["in_flywheel"] = nid in scc_of
    for e in edges:
        e["flywheel"] = (e["rel"] == "CAUSES" and e["from_id"] in scc_of
                          and scc_of.get(e["from_id"]) == scc_of.get(e["to_id"]))


def nodes_in_narratives(conn, entity_id: int) -> list[dict]:
    """이 노드가 등장하는 내러티브(주제별 최신 버전) — related_narratives의 노드 단위 버전
    (세계관 뷰 디테일 패널용)."""
    rows = conn.execute("""
        SELECT DISTINCT n.id, n.topic, n.title FROM narratives n
        JOIN (SELECT topic, MAX(version) mv FROM narratives GROUP BY topic) l
          ON l.topic = n.topic AND l.mv = n.version
        JOIN entity_relations er ON er.narrative_id = n.id
        WHERE er.src_id = ? OR er.dst_id = ?""", (entity_id, entity_id)).fetchall()
    return [dict(r) for r in rows]
