"""인물 홈·상세 읽기 (ia-redesign §4.23.4 A·B, 1단계) — 저장분만 읽는다. LLM 0.

- 묶인 이름(소프트 병합)은 대표 인물 한 사람으로 센다(pipeline/people).
- 기록 = 1단계에서는 구루 전제(pipeline/era layer_premises)를 '누가' 대응 표(people.WHO)로 사람에 붙인 것.
- 블록 단위 실패: 전제 원장 계산이 실패해도 팔로우·급증·본인 글은 그대로 준다(recorded_status·premises_status='error').
"""
from __future__ import annotations

from pipeline import people

RISING_LIMIT = 10
FOLLOWED_LIMIT = 30
OWN_LIMIT = 50
CITED_LIMIT = 5


def _role(r: dict | None) -> dict | None:
    return {k: r[k] for k in ("role", "org", "org_code", "title", "source")} if r else None


def _row(r: dict, roles: dict, records: dict) -> dict:
    return {"entity_id": r["entity_id"], "name": r["name"], "role": _role(roles.get(r["entity_id"])),
            "doc_count": r["doc_count"], "mentions_7d": r["mentions_7d"], "delta_7d": r["delta_7d"],
            "last_doc_title": r["last_doc_title"], "last_doc_id": r["last_doc_id"], "last_doc_at": r["last_doc_at"],
            "top_stocks": r["top_stocks"], "following": r["following"], "records": len(records.get(r["entity_id"], []))}


def home(conn) -> dict:
    from routers.spine_person import aggregate_people
    rows = aggregate_people(conn)
    by_id = {r["entity_id"]: r for r in rows}
    followed_rows = [r for r in rows if r["following"]]
    roles = people.roles(conn)
    try:
        prem, by_person = people.premises_by_person(conn)
        status = "ok"
    except Exception:  # noqa: BLE001 — 전제 원장 실패: 이 블록만 오류
        prem, by_person, status = [], {}, "error"

    followed = sorted(followed_rows, key=lambda r: (-r["mentions_7d"], -r["doc_count"]))[:FOLLOWED_LIMIT]
    followed_ids = {r["entity_id"] for r in followed_rows}
    rising = sorted([r for r in rows if r["entity_id"] not in followed_ids and r["delta_7d"] > 0],
                    key=lambda r: (-r["delta_7d"], -r["mentions_7d"], -r["doc_count"]))[:RISING_LIMIT]

    # 기록이 있는 인물 — 전제 순서대로 사람을 모은다(인물 엔티티가 없는 이름도 텍스트로)
    recorded: list[dict] = []
    seen: dict[str, dict] = {}
    for p in prem:
        for w in p["who_people"]:
            if w["kind"] != "person":
                continue
            base = w["label"].split("(")[0].strip()
            k = f"id:{w['entity_id']}" if w["entity_id"] else f"name:{base}"
            if k not in seen:
                eid = w["entity_id"]
                name = (by_id.get(eid) or {}).get("name") if eid else None
                if eid and not name:
                    r = conn.execute("SELECT name FROM entities WHERE id=?", (eid,)).fetchone()
                    name = r["name"] if r else None
                fallback = people.WHO.get(base, ("person", [base]))[1]
                seen[k] = {"entity_id": eid, "name": name or (fallback[0] if fallback else base),
                           "role": _role(roles.get(eid)) if eid else None,
                           "doc_count": (by_id.get(eid) or {}).get("doc_count", 0) if eid else 0, "premises": []}
                recorded.append(seen[k])
            seen[k]["premises"].append({"key": p["key"], "claim": p["claim"], "status": p["status"]})
    recorded.sort(key=lambda r: (-len(r["premises"]), -r["doc_count"]))

    records = {pid: ps for pid, ps in by_person.items()}
    shown = {r["entity_id"] for r in followed} | {r["entity_id"] for r in rising} | {r["entity_id"] for r in recorded if r["entity_id"]}
    role_counts = {"all": len(shown)}
    for k in ("policy", "executive", "guru"):
        role_counts[k] = sum(1 for i in shown if (roles.get(i) or {}).get("role") == k)
    as_of = max((r["last_doc_at"] for r in rows if r["last_doc_at"]), default=None)
    return {
        "summary": {"followed": len(followed_rows), "followed_mentions_7d": sum(r["mentions_7d"] for r in followed_rows),
                    "recorded_people": len(recorded), "premises": len(prem),
                    "mentioned": len(rows), "mentioned_2plus": sum(1 for r in rows if r["doc_count"] >= 2)},
        "role_counts": role_counts,
        "followed": [_row(r, roles, records) for r in followed],
        "recorded": recorded, "recorded_status": status,
        "rising": [_row(r, roles, records) for r in rising],
        "as_of": as_of,
    }


def _docs(conn, ids: list[int], link_types: tuple[str, ...] | None, exclude: set[int] = frozenset()) -> list[dict]:
    q = ",".join("?" * len(ids))
    lt = f"AND el.link_type IN ({','.join('?' * len(link_types))})" if link_types else "AND el.link_type != 'author'"
    rows = conn.execute(f"""SELECT DISTINCT rd.id, rd.title, rd.published_at, rd.source_type
        FROM entity_links el JOIN raw_documents rd ON rd.id = el.doc_id
        WHERE el.entity_id IN ({q}) {lt} ORDER BY rd.published_at DESC""", (*ids, *(link_types or ()))).fetchall()
    return [{"id": r["id"], "title": r["title"] or "(제목 없음)", "published_at": r["published_at"], "source_type": r["source_type"]}
            for r in rows if r["id"] not in exclude]


def detail(conn, requested: int) -> dict | None:
    """id → 상세. 묶인 이름이면 대표 인물로. 인물이 아니면 None."""
    from pipeline.source_dossier import get_cached, profile_hash
    from routers.spine_person import PROFILE_DOCS, _recent_docs
    pid = people.resolve_id(conn, requested)
    if not pid:
        return None
    ent = conn.execute("SELECT id, name FROM entities WHERE id=?", (pid,)).fetchone()
    ids = people.members(conn, pid)
    q = ",".join("?" * len(ids))
    merged = []
    for r in conn.execute(f"""SELECT e.id, e.name, e.type, m.rule,
            (SELECT COUNT(DISTINCT doc_id) FROM entity_links l WHERE l.entity_id=e.id) docs
            FROM entities e JOIN entity_merges m ON m.old_entity_id=e.id AND m.reverted_at IS NULL
            WHERE e.id IN ({q}) AND e.id != ? ORDER BY docs DESC, e.id""", (*ids, pid)):
        # 화면에는 대표와 다른 표기만 한 번씩 — 추출 잔여물("{'name': …}")은 안의 이름으로, 같은 이름의 분류 교정은 뺀다
        shown = people.canon(r["name"])[0] if r["rule"] == "cleanup" and people._JUNK.match(r["name"]) else r["name"]
        if shown == ent["name"] or any(m["name"] == shown for m in merged):
            continue
        merged.append({"entity_id": r["id"], "name": shown, "type": r["type"], "docs": r["docs"], "rule": r["rule"]})

    own = _docs(conn, ids, ("author",))
    own_ids = {d["id"] for d in own}
    mentions = _docs(conn, ids, None)            # 언급(본인 글 링크 제외 — 본인 글이 '언급'으로도 걸린 경우는 남는다)
    cited = [d for d in mentions if d["id"] not in own_ids]
    dates = [d["published_at"] for d in mentions if d["published_at"]]
    flow: dict[str, dict] = {}
    for d in own:
        y = (d["published_at"] or "")[:4]
        if y:
            flow.setdefault(y, {"year": y, "own": 0, "cited": 0})["own"] += 1
    for d in cited:
        y = (d["published_at"] or "")[:4]
        if y:
            flow.setdefault(y, {"year": y, "own": 0, "cited": 0})["cited"] += 1

    try:
        prem, by_person = people.premises_by_person(conn)
        mine, pstatus = by_person.get(pid, []), "ok"
    except Exception:  # noqa: BLE001
        mine, pstatus = [], "error"
    premises = []
    for p in mine:
        said = min((s["date"] for s in p["sources"] if s.get("date")), default=None)
        co = [w for w in p["who_people"] if w["entity_id"] != pid]
        premises.append({"key": p["key"], "claim": p["claim"], "status": p["status"], "kind": p["kind"],
                         "evidence": p["evidence"], "rule": p["rule"], "sources": p["sources"], "said_at": said, "co_holders": co})

    co = conn.execute(f"""SELECT e2.id entity_id, e2.name, el2.link_type, e2.aliases, COUNT(DISTINCT el.doc_id) c
        FROM entity_links el
        JOIN entity_links el2 ON el2.doc_id = el.doc_id AND el2.entity_id NOT IN ({q})
        JOIN entities e2 ON el2.entity_id = e2.id AND e2.status IS NOT 'merged'
        WHERE el.entity_id IN ({q}) AND el.link_type != 'author'
          AND el2.link_type IN ('stock','industry','topic','person')
        GROUP BY e2.id, el2.link_type ORDER BY c DESC LIMIT 12""", (*ids, *ids)).fetchall()

    rel = conn.execute(f"""
        SELECT r.id, CASE WHEN r.src_id IN ({q}) THEN 'out' ELSE 'in' END direction, r.rel_type,
               o.id other_id, o.name other_name, o.type other_type, o.aliases other_aliases,
               r.mechanism, r.epistemic_type, r.created_at, n.topic, n.superseded_at,
               (SELECT COALESCE(NULLIF(l.title, ''), l.topic) FROM narratives l
                 WHERE l.topic = n.topic ORDER BY l.version DESC LIMIT 1) latest_title
        FROM entity_relations r
        JOIN entities o ON o.id = CASE WHEN r.src_id IN ({q}) THEN r.dst_id ELSE r.src_id END
        LEFT JOIN narratives n ON n.id = r.narrative_id
        WHERE r.src_id IN ({q}) OR r.dst_id IN ({q})
        ORDER BY r.created_at DESC, r.id DESC LIMIT 20""", (*ids, *ids, *ids, *ids)).fetchall()

    docs = _recent_docs(conn, pid, PROFILE_DOCS)
    cached = get_cached(conn, "person", ent["name"])
    stale = bool(docs) and (not cached or cached["doc_ids_hash"] != profile_hash(docs))
    new_since = None
    if cached:
        new_since = conn.execute(f"""SELECT COUNT(DISTINCT el.doc_id) FROM entity_links el JOIN raw_documents rd ON rd.id = el.doc_id
            WHERE el.entity_id IN ({q}) AND el.link_type != 'author' AND rd.fetched_at > ?""", (*ids, cached["created_at"])).fetchone()[0]
    following = conn.execute(f"SELECT 1 FROM follows WHERE entity_id IN ({q})", ids).fetchone() is not None
    return {
        "entity_id": pid, "requested_id": requested, "name": ent["name"], "role": _role(people.roles(conn, [pid]).get(pid)),
        "merged_names": merged, "following": following,
        "mentions": {"count": len(mentions), "first_at": min(dates) if dates else None, "last_at": max(dates) if dates else None},
        "own_docs": own[:OWN_LIMIT], "own_total": len(own),
        "own_source": next((org for pre, (n, org) in people.MEMO_AUTHORS.items() if people.resolve_name(conn, n) == pid), None),
        "cited": cited[:CITED_LIMIT], "cited_total": len(cited),
        "flow": [flow[y] for y in sorted(flow)],
        "premises": premises, "premises_status": pstatus,
        "co_entities": [{"entity_id": r["entity_id"], "name": r["name"], "link_type": r["link_type"], "aliases": r["aliases"],
                         "count": r["c"]} for r in co],
        "relations": [{"id": r["id"], "direction": r["direction"], "rel_type": r["rel_type"], "other_id": r["other_id"],
                       "other_name": r["other_name"], "other_type": r["other_type"], "other_aliases": r["other_aliases"],
                       "mechanism": r["mechanism"], "epistemic_type": r["epistemic_type"] or "fact", "created_at": r["created_at"],
                       "narrative_topic": r["topic"], "narrative_title": r["latest_title"],
                       "narrative_superseded": bool(r["superseded_at"])} for r in rel],
        "profile": {"status": "cached", "digest": cached["digest"], "insights": cached["insights"],
                    "created_at": cached["created_at"]} if cached else None,
        "profile_stale": stale, "new_since_profile": new_since,
    }
