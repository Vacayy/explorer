"""포트폴리오 공통 변수(노출) — 보유 종목들이 함께 기대는 변수와 그 변수에 걸린 비중 (docs/specs/portfolio-intelligence.md §1).

인과 그래프 커버리지가 종목마다 크게 달라(2026-10-08: SK하이닉스 70간선, 두산테스나 0) 세 출처를 합치고 출처를 표시한다.
  graph     — 인과 그래프 상류(근거 있는 간선만, 2단계, 신뢰도 곱). 방향(+/−) 있음
  comention — 최근 180일 같은 문서에 붙은 주제·산업. 전체 대비 향상도(lift)로 일반 태그를 거른다
  chain     — 밸류체인 단계(같은 체인의 어느 단계에 있나)
결정적 계산, LLM 0. 입력은 보유 종목과 비중(%)뿐 — 금액 없음.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

GRAPH_STATUSES = ("document", "verified")   # legacy_unverified·scenario·unverified 제외
MIN_PATH_CONF = 0.2
COMENTION_DAYS = 180
MIN_LIFT, MIN_DOCS, MIN_SHARE = 2.5, 3, 0.05
# 글의 '성격' 태그 — 무엇에 관한 글인지가 아니라 어떤 종류의 글인지라 변수가 아니다(enrich 분류 체계, 2026-10-08 실측)
GENRE_TAGS = {"산업동향", "수급", "실적분석", "시장동향", "밸류에이션", "투자전략", "투자심리", "매크로", "IPO/이벤트", "이벤트", "주주환원"}
TOP = 15


def company_entity(conn: sqlite3.Connection, code: str) -> sqlite3.Row | None:
    return conn.execute("SELECT id, name FROM entities WHERE type='company' AND aliases=? ORDER BY id LIMIT 1", (code,)).fetchone()


def _anchor_ids(conn: sqlite3.Connection, ent: sqlite3.Row) -> list[int]:
    """회사 노드 + 이름이 회사명으로 시작하는 사건 노드('원익IPS 수주 잔고 급증' 등은 회사 노드에 안 붙어 있다)."""
    ids = [ent["id"]] + [r["id"] for r in conn.execute(
        "SELECT id FROM entities WHERE type='event' AND name LIKE ? AND id != ?", (ent["name"] + "%", ent["id"]))]
    return ids


def _upstream(conn: sqlite3.Connection, node_ids: list[int]) -> list[tuple[int, float, str | None]]:
    """(동인 id, 신뢰도, 방향). CAUSES는 src→노드, BENEFITS_FROM은 노드→dst(수혜 → 동인)."""
    if not node_ids:
        return []
    q, st = ",".join("?" * len(node_ids)), ",".join("?" * len(GRAPH_STATUSES))
    rows = conn.execute(
        f"SELECT src_id AS d, confidence c, effect_direction e FROM entity_relations WHERE rel_type='CAUSES' AND dst_id IN ({q}) "
        f"AND source_status IN ({st}) UNION ALL "
        f"SELECT dst_id, confidence, effect_direction FROM entity_relations WHERE rel_type='BENEFITS_FROM' AND src_id IN ({q}) "
        f"AND source_status IN ({st})", (*node_ids, *GRAPH_STATUSES, *node_ids, *GRAPH_STATUSES)).fetchall()
    return [(r["d"], r["c"] or 0.0, r["e"]) for r in rows]


def graph_drivers(conn: sqlite3.Connection, code: str) -> dict[int, dict]:
    ent = company_entity(conn, code)
    if not ent:
        return {}
    anchors = _anchor_ids(conn, ent)
    out: dict[int, dict] = {}
    sign = {"positive": 1, "negative": -1}
    for d, c, e in _upstream(conn, anchors):
        if c < MIN_PATH_CONF or d in anchors:
            continue
        s = sign.get(e, 0)
        if d not in out or c > out[d]["conf"]:
            out[d] = {"conf": c, "sign": s, "hops": 1}
        for d2, c2, e2 in _upstream(conn, [d]):
            conf = c * c2
            if conf < MIN_PATH_CONF or d2 in anchors:
                continue
            if d2 not in out or conf > out[d2]["conf"]:
                out[d2] = {"conf": conf, "sign": s * sign.get(e2, 0), "hops": 2}
    return out


def comention_drivers(conn: sqlite3.Connection, code: str) -> dict[int, dict]:
    """같은 문서에 붙은 주제·산업. 문서마다 1/(그 문서의 종목 수)로 가중 — 종목 수십 개를 나열한 시황 글이
    소형주의 주제 분포를 오염시킨다(2026-10-08 두산테스나: 52·56종목 나열 글에서 '바이오'·'2차전지'가 잡힘)."""
    ent = company_entity(conn, code)
    if not ent:
        return {}
    since = f"-{COMENTION_DAYS} day"
    docs = {r["doc_id"]: 1.0 / max(1, r["n"]) for r in conn.execute(
        "SELECT el.doc_id, (SELECT count(*) FROM entity_links x WHERE x.doc_id=el.doc_id AND x.link_type='stock') n "
        "FROM entity_links el JOIN raw_documents rd ON rd.id=el.doc_id "
        "WHERE el.link_type='stock' AND el.entity_id=? AND rd.published_at >= datetime('now', ?) GROUP BY el.doc_id", (ent["id"], since))}
    if len(docs) < MIN_DOCS:
        return {}
    total_w = sum(docs.values())
    total = conn.execute("SELECT count(*) FROM raw_documents WHERE published_at >= datetime('now', ?)", (since,)).fetchone()[0] or 1
    q = ",".join("?" * len(docs))
    per: dict[int, list[int]] = defaultdict(list)
    for r in conn.execute(f"SELECT el.entity_id, el.doc_id FROM entity_links el JOIN entities e ON e.id=el.entity_id "
                          f"WHERE el.doc_id IN ({q}) AND el.link_type IN ('topic','industry')", tuple(docs)):
        per[r["entity_id"]].append(r["doc_id"])
    genre = {r["id"] for r in conn.execute(f"SELECT id FROM entities WHERE name IN ({','.join('?' * len(GENRE_TAGS))})", tuple(GENRE_TAGS))}
    out = {}
    for eid, ds in per.items():
        ds = set(ds)
        if len(ds) < MIN_DOCS or eid in genre:
            continue
        share = sum(docs[d] for d in ds) / total_w
        base = conn.execute("SELECT count(DISTINCT el.doc_id) FROM entity_links el JOIN raw_documents rd ON rd.id=el.doc_id "
                            "WHERE el.entity_id=? AND rd.published_at >= datetime('now', ?)", (eid, since)).fetchone()[0] or 1
        lift = share / (base / total)
        if share >= MIN_SHARE and lift >= MIN_LIFT:
            out[eid] = {"docs": len(ds), "share": round(share, 2), "lift": round(lift, 1)}
    return out


def chain_stage(conn: sqlite3.Connection, code: str, comention_names: set[str]) -> tuple[str, str | None] | None:
    """(체인, 단계|None). 체인은 동시 언급 주제가 가장 많이 겹치는 그룹(업종 표 분류가 있으면 그 분류가 든 그룹 우선),
    단계는 업종 표 분류가 있을 때만 — 주제로 단계를 추측하면 후공정 테스트 기업이 '제조'로 잡힌다."""
    cat = conn.execute("SELECT category FROM industry_members WHERE stock_code=? LIMIT 1", (code,)).fetchone()
    key = (cat["category"] or "").split("·")[0] if cat else ""
    groups: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    for r in conn.execute("SELECT group_name, stage_name, themes_json FROM value_chains ORDER BY group_name, stage_idx"):
        groups[r["group_name"]].append((r["stage_name"], json.loads(r["themes_json"] or "[]")))

    def hits(themes):
        return sum(1 for t in themes if any(t.split("(")[0].strip() in n or n in t for n in comention_names))
    scored = []
    for g, stages in groups.items():
        stage = next((s for s, _ in stages if key and key in s), None)
        h = sum(hits(t) for _, t in stages)
        scored.append((h + (3 if stage and h else 0), g, stage if h else None))   # 주제 근거 없는 체인에 분류 이름만으로 붙지 않게
    best = max(scored, default=(0, None, None))
    return (best[1], best[2]) if best[0] > 0 else None


_cache: dict[tuple, tuple[float, dict]] = {}


def cached_exposure(conn: sqlite3.Connection, holdings: list[dict], ttl: int = 600) -> dict:
    """같은 보유 구성이면 10분 재사용 — 화면의 공통 변수·이벤트 카드가 같은 계산(~1.5s)을 나눠 쓴다."""
    import time
    key = tuple(sorted((h["code"], round(h["weight_pct"] or 0, 1)) for h in holdings))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    result = exposure(conn, holdings)
    _cache[key] = (time.time(), result)
    return result


def chains_of(conn: sqlite3.Connection, holdings: list[dict]) -> set[str]:
    return {v["chain"] for v in cached_exposure(conn, holdings)["coverage"].values() if v.get("chain")}


def exposure(conn: sqlite3.Connection, holdings: list[dict]) -> dict:
    """holdings: [{code, name, weight_pct}] → 공통 변수 상위 목록 + 출처별 커버리지."""
    drivers: dict[str, dict] = {}
    coverage = {}

    def add(key, name, typ, h, source, extra=None):
        d = drivers.setdefault(key, {"key": key, "name": name, "type": typ, "holdings": {}, "sources": set(), "direction": set(),
                                     "conf": 0.0, "hops": 9})
        d["holdings"][h["code"]] = h["weight_pct"] or 0.0
        d["sources"].add(source)
        if extra:
            d["conf"], d["hops"] = max(d["conf"], extra["conf"]), min(d["hops"], extra["hops"])
            if extra.get("sign"):
                d["direction"].add("+" if extra["sign"] > 0 else "−")

    names = {}
    for h in holdings:
        g, cm = graph_drivers(conn, h["code"]), comention_drivers(conn, h["code"])
        ids = set(g) | set(cm)
        if ids:
            q = ",".join("?" * len(ids))
            names.update({r["id"]: (r["name"], r["type"]) for r in conn.execute(f"SELECT id, name, type FROM entities WHERE id IN ({q})", tuple(ids))})
        for i, v in g.items():          # 같은 이름의 sector·theme 엔티티가 따로 있어 이름으로 합친다
            add(f"n:{names[i][0]}", *names[i], h, "graph", v)
        for i in cm:
            add(f"n:{names[i][0]}", *names[i], h, "comention")
        st = chain_stage(conn, h["code"], {names[i][0] for i in cm})
        if st:
            add(f"chain:{st[0]}", f"{st[0]} 밸류체인", "chain", h, "chain")
        coverage[h["code"]] = {"graph": len(g), "comention": len(cm), "chain": st[0] if st else None, "stage": st[1] if st else None}

    held = {h["code"] for h in holdings}
    held_names = {h["name"] for h in holdings}
    out = []
    for d in drivers.values():
        if d["name"] in held_names and len(d["holdings"]) == 1 and d["name"] == next(h["name"] for h in holdings if h["code"] in d["holdings"]):
            continue
        out.append({"key": d["key"], "name": d["name"], "type": d["type"],
                    "exposure_pct": round(sum(d["holdings"].values()), 1),
                    "holdings": sorted(d["holdings"], key=lambda c: -d["holdings"][c]),
                    "sources": sorted(d["sources"]),
                    # 업종·회사 묶음의 방향은 간선 하나의 잡음인 경우가 많아(2026-10-08 '반도체 → SK하이닉스 −') 테마·사건·매크로·정책만
                    "direction": ("".join(sorted(d["direction"])) or None) if d["type"] in ("theme", "event", "macro", "policy") else None,
                    "confidence": round(d["conf"], 2) if d["conf"] else None, "hops": d["hops"] if d["hops"] < 9 else None})
    # 여러 종목·여러 출처에 걸친 변수를 위로
    out.sort(key=lambda d: (-len(d["holdings"]), -d["exposure_pct"], -len(d["sources"]), d["hops"] or 9, -(d["confidence"] or 0), d["name"]))
    return {"drivers": out[:TOP], "coverage": coverage, "held": sorted(held)}
