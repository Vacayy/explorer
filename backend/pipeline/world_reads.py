"""월드모델 읽기 전용 조회 — '지금' 랜딩·서사 체크포인트·홈 위젯 (docs/specs/world-model.md).

전부 저장된 행만 읽는다. LLM·subprocess를 부르는 경로(narrative_diff의 게으른 haiku 요약,
worldview/narrative compute)는 쓰지 않는다 — 위젯이 열릴 때마다 생성이 돌면 안 되기 때문이다.
"""
from pipeline.mega_narrative import list_mega
from pipeline.narrative import _version_diff, causal_subgraph, change_summary_fallback, narrative_grounding
from pipeline.narrative_graph import narrative_chain
from pipeline.worldview import gather as worldview_gather, get_cached as worldview_cached, inputs_hash

STALE_DAYS = 30
EDGE_TRUST = ("verified", "document")   # 출처를 원문에서 확인한 엣지만 '내 종목' 연결로 쓴다


def _edge_brief(e: dict) -> dict:
    return {"from": e["from"], "to": e["to"], "rel": e["rel"], "effect_direction": e.get("effect_direction")}


def _latest_topic_rows(conn) -> dict[str, dict]:
    """주제별 최신 버전(topic 종류, 제목 있는 것)."""
    rows = conn.execute("""
        SELECT n.id, n.topic, n.version, n.title, n.category, n.created_at, n.drift_summary, n.core_question
        FROM narratives n
        JOIN (SELECT topic, MAX(version) mv FROM narratives WHERE COALESCE(kind,'topic')='topic' GROUP BY topic) l
          ON l.topic=n.topic AND l.mv=n.version
        WHERE n.title IS NOT NULL AND COALESCE(n.kind,'topic')='topic'""").fetchall()
    return {r["topic"]: dict(r) for r in rows}


def big_picture(conn) -> dict:
    """이번 주 큰 그림 — 살아 있는 메가 서사 + 저장된 세계관 브리핑(생성하지 않는다)."""
    mega = list_mega(conn)
    cached = worldview_cached(conn)
    worldview = None
    if cached:
        m = worldview_gather(conn)
        worldview = {"briefing": cached["digest"], "created_at": cached["created_at"],
                     "stale": cached["doc_ids_hash"] != inputs_hash(m)}
    dates = [m["created_at"] for m in mega if m["created_at"]] + ([worldview["created_at"]] if worldview else [])
    return {"mega": mega, "worldview": worldview, "as_of": max(dates) if dates else None}


def narrative_changes(conn, days: int = 7, limit: int = 20) -> dict:
    """최근 days일에 새 버전이 나온 주제 — 바뀐 것 한 줄(저장분) + 직전 버전 대비 추가·삭제 고리(결정적).
    change_summary는 생성 때 저장된 1~2문장, 없는 옛 버전은 드리프트 첫 문장을 결정적으로 줄여 쓴다."""
    rows = conn.execute("""
        SELECT n.id, n.topic, n.version, n.title, n.category, n.created_at, n.drift_summary, n.change_summary,
               (SELECT COUNT(*) FROM narratives n2 WHERE n2.topic=n.topic
                  AND n2.created_at >= datetime('now', ?)) versions_in_window
        FROM narratives n
        JOIN (SELECT topic, MAX(version) mv FROM narratives WHERE COALESCE(kind,'topic')='topic' GROUP BY topic) l
          ON l.topic=n.topic AND l.mv=n.version
        WHERE n.title IS NOT NULL AND COALESCE(n.kind,'topic')='topic'
          AND n.created_at >= datetime('now', ?)
        ORDER BY n.created_at DESC LIMIT ?""", (f"-{days} days", f"-{days} days", limit)).fetchall()
    items = []
    for r in rows:
        d = _version_diff(conn, r["id"])
        ok = d["status"] == "ok"
        added = d.get("added_edges", []) if ok else []
        removed = d.get("removed_edges", []) if ok else []
        is_first = d["status"] == "no_prior_version"
        items.append({
            "topic": r["topic"], "narrative_id": r["id"], "version": r["version"], "title": r["title"],
            "category": r["category"], "created_at": r["created_at"], "drift_summary": r["drift_summary"],
            "change_summary": None if is_first else (r["change_summary"] or change_summary_fallback(r["drift_summary"])),
            "versions_in_window": r["versions_in_window"], "is_first": is_first,
            "added_count": len(added), "removed_count": len(removed),
            "added_edges": [_edge_brief(e) for e in added[:5]],
            "removed_edges": [_edge_brief(e) for e in removed[:5]],
        })
    return {"days": days, "items": items, "as_of": items[0]["created_at"] if items else None}


def contested(conn, limit: int = 10) -> dict:
    """흔들리는 전제 — 활성 지식 중 충돌 중인 것 + 가장 최근 반례 문서."""
    rows = conn.execute("""
        SELECT k.id, k.statement, k.pace_layer, k.contested_at,
               (SELECT COUNT(*) FROM knowledge_evidence WHERE knowledge_id=k.id AND stance='refute') refute,
               (SELECT COUNT(*) FROM knowledge_evidence WHERE knowledge_id=k.id AND stance='support') support
        FROM knowledge k
        WHERE k.review_status='active' AND k.epistemic_status='contested' AND k.valid_to IS NULL
        ORDER BY k.contested_at DESC LIMIT ?""", (limit,)).fetchall()
    items = []
    for r in rows:
        doc = conn.execute("""
            SELECT ev.doc_id, rd.title, ev.observed_at FROM knowledge_evidence ev
            LEFT JOIN raw_documents rd ON rd.id=ev.doc_id
            WHERE ev.knowledge_id=? AND ev.stance='refute' ORDER BY ev.observed_at DESC LIMIT 1""",
            (r["id"],)).fetchone()
        items.append({**dict(r), "latest_refute": dict(doc) if doc else None})
    return {"items": items, "as_of": items[0]["contested_at"] if items else None}


def _member_companies(conn) -> list[dict]:
    """종목 묶음(보유·관심) 종목 → 회사 엔티티. 묶음 종류를 함께 들고 간다."""
    rows = conn.execute("""
        SELECT m.stock_code, g.kind, e.id entity_id, e.name
        FROM stock_group_members m JOIN stock_groups g ON g.id=m.group_id
        LEFT JOIN entities e ON e.id = (SELECT id FROM entities WHERE type='company' AND aliases=m.stock_code
                                        ORDER BY id LIMIT 1)""").fetchall()
    by_code: dict[str, dict] = {}
    for r in rows:
        s = by_code.setdefault(r["stock_code"], {"stock_code": r["stock_code"], "name": r["name"],
                                                "entity_id": r["entity_id"], "kinds": []})
        if r["kind"] not in s["kinds"]:
            s["kinds"].append(r["kind"])
    return list(by_code.values())


def _stock_topic_links(conn, entity_id: int, topics: set[str]) -> dict[str, dict]:
    """회사 하나 → 서사 주제. (a) 그 회사가 걸린 신뢰 엣지를 만든 서사, (b) 신뢰 엣지 건너편 노드가 서사 주제."""
    marks = ",".join("?" * len(EDGE_TRUST))
    links: dict[str, dict] = {}
    for r in conn.execute(f"""
        SELECT n.topic FROM entity_relations er JOIN narratives n ON n.id=er.narrative_id
        WHERE (er.src_id=? OR er.dst_id=?) AND er.rel_type IN ('CAUSES','BENEFITS_FROM')
          AND er.source_status IN ({marks})""", (entity_id, entity_id, *EDGE_TRUST)):
        if r["topic"] in topics:
            links.setdefault(r["topic"], {"edges": 0, "via": "edge"})["edges"] += 1
    for r in conn.execute(f"""
        SELECT o.name FROM entity_relations er
        JOIN entities o ON o.id = CASE WHEN er.src_id=? THEN er.dst_id ELSE er.src_id END
        WHERE (er.src_id=? OR er.dst_id=?) AND er.rel_type IN ('CAUSES','BENEFITS_FROM')
          AND er.source_status IN ({marks})""", (entity_id, entity_id, entity_id, *EDGE_TRUST)):
        if r["name"] in topics:
            links.setdefault(r["name"], {"edges": 0, "via": "neighbor"})["edges"] += 1
    return links


def stock_narratives(conn, per_stock: int = 3) -> dict:
    """내 종목을 움직이는 서사 — 묶음 종목별 걸린 서사(주제별 최신본) 상위 per_stock개."""
    latest = _latest_topic_rows(conn)
    topics = set(latest)
    members = _member_companies(conn)
    stocks = []
    for s in members:
        if s["entity_id"] is None:
            continue
        links = _stock_topic_links(conn, s["entity_id"], topics)
        if not links:
            continue
        # 엣지가 많은 서사 먼저, 같으면 최근에 갱신된 것
        ranked = sorted(links.items(), key=lambda kv: (kv[1]["edges"], latest[kv[0]]["created_at"] or ""), reverse=True)
        narratives = [{"topic": t, "narrative_id": latest[t]["id"], "title": latest[t]["title"],
                       "version": latest[t]["version"], "created_at": latest[t]["created_at"],
                       "drift_summary": latest[t]["drift_summary"], "edges": v["edges"], "via": v["via"]}
                      for t, v in ranked[:per_stock]]
        newest = max(narratives, key=lambda n: n["created_at"] or "")
        stocks.append({"stock_code": s["stock_code"], "name": s["name"], "kinds": s["kinds"],
                       "narratives": narratives, "latest_drift": newest["drift_summary"],
                       "latest_at": newest["created_at"]})
    stocks.sort(key=lambda x: x["latest_at"] or "", reverse=True)
    return {"stocks": stocks, "members": len(members), "covered": len(stocks),
            "as_of": stocks[0]["latest_at"] if stocks else None}


def _company_code(conn, name: str) -> str | None:
    r = conn.execute("SELECT aliases FROM entities WHERE type='company' AND name=? LIMIT 1", (name,)).fetchone()
    return r["aliases"] if r else None


def checkpoint(conn, topic: str) -> dict:
    """서사 상세 상단 체크포인트 — 핵심질문(추적 여부) · 흔들릴 조건 · 수혜 섹터·종목 · 걸린 내 종목."""
    row = conn.execute("""
        SELECT id, title, core_question FROM narratives
        WHERE topic=? AND COALESCE(kind,'topic')='topic' ORDER BY version DESC LIMIT 1""", (topic,)).fetchone()
    if not row:
        return {"status": "empty", "topic": topic}
    core = row["core_question"] or (conn.execute(
        "SELECT core_question FROM narratives WHERE topic=? AND core_question IS NOT NULL "
        "ORDER BY version DESC LIMIT 1", (topic,)).fetchone() or {"core_question": None})["core_question"]

    qrows = conn.execute("""
        SELECT q.id, q.text, q.status, q.lead_verdict, q.confirm_verdict FROM questions q
        WHERE q.status != 'dismissed' AND q.narrative_id IN (SELECT id FROM narratives WHERE topic=?)
        ORDER BY q.status='tracking' DESC, q.text=? DESC, q.id DESC""", (topic, core or "")).fetchall()
    question = dict(qrows[0]) if qrows else None

    falsifiers: list[dict] = []
    for g in narrative_grounding(conn, row["id"])["grounding"]:
        falsifiers += [{"condition": f, "source": "knowledge", "about": g["statement"]} for f in g["falsifiers"]]
    if question and question["status"] == "tracking":
        falsifiers += [{"condition": r["falsifier"], "source": "question", "about": r["text"]} for r in conn.execute(
            "SELECT text, falsifier FROM sub_questions WHERE question_id=? AND falsifier IS NOT NULL", (question["id"],))]
    seen: set[str] = set()
    falsifiers = [f for f in falsifiers if not (f["condition"] in seen or seen.add(f["condition"]))][:6]

    beneficiaries: dict[str, dict] = {}

    def add(name: str, typ: str, via: str):
        if typ in ("sector", "company", "theme") and name != topic and name not in beneficiaries:
            beneficiaries[name] = {"name": name, "type": typ, "via": via,
                                   "stock_code": _company_code(conn, name) if typ == "company" else None}

    for p in narrative_chain(conn, row["id"])["paths"]:
        if p["reaches_sector"]:
            last = p["nodes"][-1]
            add(last["name"], last["type"], "chain")
        for n in p["nodes"]:
            if n["type"] == "company":
                add(n["name"], n["type"], "chain")
    for e in causal_subgraph(conn, row["id"])["edges"]:
        if e["rel"] == "BENEFITS_FROM":   # src = 수혜 쪽
            add(e["from"], e["from_type"], "claim")

    my_stocks = []
    for s in _member_companies(conn):
        if s["entity_id"] is None:
            continue
        link = _stock_topic_links(conn, s["entity_id"], {topic}).get(topic)
        if link:
            my_stocks.append({"stock_code": s["stock_code"], "name": s["name"], "kinds": s["kinds"], "edges": link["edges"]})
    return {"status": "ok", "topic": topic, "narrative_id": row["id"], "title": row["title"],
            "core_question": core, "question": question, "falsifiers": falsifiers,
            "beneficiaries": list(beneficiaries.values())[:10], "my_stocks": my_stocks}

