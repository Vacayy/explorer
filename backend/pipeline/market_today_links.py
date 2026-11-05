"""Market Today 화두 → 내러티브 연결 · 내러티브 후보 (ia-redesign §9, docs/specs/market-today.md). LLM 없음, 결정적.

짝 찾기(§9.1) — 화두 하나와 살아 있는 내러티브의 주제(`narratives.topic` = `entities.name`)를 비교한다.
  1 태그 일치: 화두 태그 하나가 주제와 같고(공백·대소문자 무시) 출처 문서 1건 이상이 그 주제에 연결돼 있다
  2 자료 겹침 + 태그 부분 일치: 그 주제에 연결된 출처 문서 2건 이상 + 화두 태그 안에 주제명이 들어 있다
  3 자료 겹침: 그 주제에 연결된 출처 문서 2건 이상
  (4 의미 유사·임베딩은 예비 — 구현하지 않았다)
문서 수는 **주제 이름 기준**으로 센다 — '지정학'처럼 같은 이름의 엔티티가 둘이어도 문서 1건은 1건.
'연결된 출처 문서' = entity_links(link_type industry|topic, 엔티티 type sector|theme) — 내러티브 재료 gather()와 같은 기준.

후보(§9.3) — 같은 정규화 태그를 공유하는 화두끼리 묶는다(공유 태그로 이어진 묶음). 살아 있는 내러티브 이름·일반어
태그는 묶는 고리로 쓰지 않는다. 2개 거래일 이상·3회차 이상이면 후보, 3회차 이상인데 하루 안이면 관찰 중.
회차 수에는 16:00 마감 정리를 넣지 않는다 — 그날 장중 회차를 다시 정리한 것이라 같은 화두가 두 번 세진다.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
WRAP_SLOT = "1600"
RULE_LABEL = {1: "태그 일치", 2: "자료 겹침 + 태그 부분 일치", 3: "자료 겹침"}
CANDIDATE_DAYS = 7          # 후보를 찾는 창(일)
CANDIDATE_MIN_DAYS = 2      # 거래일
CANDIDATE_MIN_SESSIONS = 3  # 회차(마감 정리 제외)
DISMISS_DAYS = 14
MERGE_MIN_OVERLAP = 2       # 합치기 제안 — 후보 출처와 새 서사 근거가 이만큼 겹치면
MERGE_NEW_DAYS = 7          # '같은 기간에 새로 생긴 서사' = 첫 버전이 후보 첫 등장 7일 전 이후
BOOST_MIN_SESSIONS = 3      # 갱신 앞당김 — 이번 주 연결 회차
BOOST_STALE_DAYS = 3        # 마지막 갱신 뒤 경과일
# 일반어 — 후보로 올리지 않고 묶는 고리로도 쓰지 않는다. 운영하면서 늘린다(§9.3)
GENERIC_TAGS = {
    "실적", "기술주", "증시심리", "증시", "주식시장", "시장", "코스피", "코스닥", "나스닥", "선물", "미국선물", "국채", "달러",
    "환율", "유가", "수급", "외국인", "기관", "개인", "주가", "급락", "급등", "기술주급락", "변동성", "업종", "투자심리",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_today_links (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    mt_id            INTEGER NOT NULL,          -- market_today.id
    item_idx         INTEGER NOT NULL,          -- 회차 안 화두 순번(items_json 인덱스)
    narrative_topic  TEXT NOT NULL,             -- narratives.topic — 버전이 바뀌어도 그대로 유효
    rule             INTEGER NOT NULL,          -- 1 태그 일치 | 2 자료 겹침+태그 부분 일치 | 3 자료 겹침
    doc_overlap      INTEGER NOT NULL,          -- 그 주제에 연결된 출처 문서 수(주제 이름 기준 중복 제거)
    created_at       TEXT DEFAULT (datetime('now')),
    UNIQUE(mt_id, item_idx, narrative_topic)
);
CREATE INDEX IF NOT EXISTS idx_mt_links_topic ON market_today_links(narrative_topic);
CREATE TABLE IF NOT EXISTS narrative_candidates (
    tag              TEXT PRIMARY KEY,          -- 묶음 대표 태그(정규화)
    name             TEXT,                      -- 보이는 이름(대표 태그 원문, 동률이면 둘)
    first_seen       TEXT,                      -- 첫 회차 거래일
    last_seen        TEXT,
    sessions_json    TEXT,                      -- [{mt_id, trade_date, slot}]
    detail_json      TEXT,                      -- {days, sessions, sources, tags, items, linked, merge_into, attempt}
    status           TEXT NOT NULL DEFAULT 'pending',   -- pending | watching | approved | dismissed
    dismissed_until  TEXT,                      -- 무시 — 이 날짜(KST)까지 다시 올리지 않는다
    narrative_topic  TEXT,                      -- 승인 — 새 서사 주제 또는 합칠 서사 주제
    updated_at       TEXT DEFAULT (datetime('now'))
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)
    try:  # 2026-11-05 — 연결을 계산한 시각. NULL이면 '아직 계산 전'(칩 줄을 그리지 않고 타임라인은 '예정')
        conn.execute("ALTER TABLE market_today ADD COLUMN links_at TEXT")
    except Exception:  # noqa: BLE001 — 이미 있으면 그대로
        pass


def norm(text: str | None) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _today_kst() -> date:
    return datetime.now(timezone.utc).astimezone(KST).date()


def week_start(today: date | None = None) -> date:
    t = today or _today_kst()
    return t - timedelta(days=t.weekday())


def _live_topics(conn) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT topic FROM narratives WHERE superseded_at IS NULL AND COALESCE(kind,'topic')='topic'")]


def _aliases(conn) -> dict[str, str]:
    """승인된 '합치기' — 후보 태그 → 합칠 서사 주제. 이후 그 태그는 그 서사와 태그 일치로 본다."""
    out = {}
    for r in conn.execute("SELECT detail_json, narrative_topic FROM narrative_candidates "
                          "WHERE status='approved' AND narrative_topic IS NOT NULL"):
        d = json.loads(r[0] or "{}")
        if d.get("mode") == "merge":
            for t in d.get("alias_tags") or []:
                out[norm(t)] = r[1]
    return out


def _item_docs(item: dict, sources: dict) -> list[int]:
    return list(dict.fromkeys(int(sources[r]["doc_id"]) for r in item.get("refs") or []
                              if r in sources and sources[r].get("doc_id")))


def _doc_topic_names(conn, doc_ids) -> dict[int, set[str]]:
    """문서 → 연결된 주제 이름 집합(이름 기준 중복 제거)."""
    ids = sorted({int(d) for d in doc_ids})
    out: dict[int, set[str]] = defaultdict(set)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = ",".join("?" * len(chunk))
        for r in conn.execute(
                f"SELECT el.doc_id, e.name FROM entity_links el JOIN entities e ON e.id=el.entity_id "
                f"WHERE el.doc_id IN ({q}) AND el.link_type IN ('industry','topic') AND e.type IN ('sector','theme')", chunk):
            out[r[0]].add(r[1])
    return out


def match_item(tags: list[str], doc_names: list[set[str]], topics: list[str], aliases: dict[str, str] | None = None) -> list[dict]:
    """화두 하나 → [{topic, rule, doc_overlap}] (순위 → 겹친 문서 수 큰 순). doc_names = 출처 문서마다 연결된 주제 이름 집합."""
    ntags = [norm(t) for t in tags if norm(t)]
    alias_hit = {aliases[t] for t in ntags if aliases and t in aliases}
    out = []
    for topic in topics:
        nt = norm(topic)
        if not nt:
            continue
        ov = sum(1 for names in doc_names if topic in names)
        if (nt in ntags and ov >= 1) or topic in alias_hit:
            rule = 1
        elif ov >= 2 and any(nt in t for t in ntags):
            rule = 2
        elif ov >= 2:
            rule = 3
        else:
            continue
        out.append({"topic": topic, "rule": rule, "doc_overlap": ov})
    out.sort(key=lambda x: (x["rule"], -x["doc_overlap"], x["topic"]))
    return out


def link_narratives(conn, mt_id: int) -> int:
    """회차 하나의 화두마다 살아 있는 내러티브 짝을 찾아 저장(다시 계산하면 덮어씀). 반환 = 연결 수."""
    ensure_schema(conn)
    row = conn.execute("SELECT items_json, sources_json FROM market_today WHERE id=?", (mt_id,)).fetchone()
    if not row:
        return 0
    items = json.loads(row["items_json"] or "[]")
    sources = json.loads(row["sources_json"] or "{}")
    per_item = [_item_docs(it, sources) for it in items]
    names = _doc_topic_names(conn, [d for ds in per_item for d in ds])
    topics, aliases = _live_topics(conn), _aliases(conn)
    conn.execute("DELETE FROM market_today_links WHERE mt_id=?", (mt_id,))
    n = 0
    for idx, (it, docs) in enumerate(zip(items, per_item)):
        for m in match_item(it.get("tags") or [], [names.get(d, set()) for d in docs], topics, aliases):
            conn.execute("INSERT INTO market_today_links (mt_id, item_idx, narrative_topic, rule, doc_overlap) VALUES (?,?,?,?,?)",
                         (mt_id, idx, m["topic"], m["rule"], m["doc_overlap"]))
            n += 1
    conn.execute("UPDATE market_today SET links_at=datetime('now') WHERE id=?", (mt_id,))
    return n


def link_since(conn, since: str | None = None, only_missing: bool = False) -> dict:
    """여러 회차를 한 번에(백필·재계산). since = 거래일 'YYYY-MM-DD'(포함), None이면 전부."""
    ensure_schema(conn)
    sql = "SELECT id FROM market_today WHERE 1=1"
    args: list = []
    if since:
        sql += " AND trade_date >= ?"
        args.append(since)
    if only_missing:
        sql += " AND links_at IS NULL"
    ids = [r[0] for r in conn.execute(sql + " ORDER BY trade_date, slot", args)]
    links = sum(link_narratives(conn, i) for i in ids)
    return {"sessions": len(ids), "links": links}


def after_session(conn, day: date) -> dict:
    """회차 생성 직후(market_today.run) — 그날과 전 거래일 회차를 다시 연결하고 후보를 갱신한다.
    앞 회차까지 다시 보는 이유: 출처 문서의 주제 연결(enrich)이 회차보다 늦게 붙을 수 있다. 결정적이라 비용이 없다."""
    r = link_since(conn, (day - timedelta(days=4)).isoformat())
    r["candidates"] = refresh_candidates(conn, today=day)
    conn.commit()
    return r


# ---------- 읽기: 화두별 칩 ----------

def _live_meta(conn) -> dict[str, dict]:
    return {r["topic"]: {"narrative_id": r["id"], "version": r["version"], "created_at": r["created_at"]}
            for r in conn.execute("SELECT id, topic, version, created_at FROM narratives "
                                  "WHERE superseded_at IS NULL AND COALESCE(kind,'topic')='topic'")}


def links_for_session(conn, mt_id: int) -> dict[int, list[dict]]:
    """회차 → {화두 순번: [{topic, narrative_id, version, created_at, rule, doc_overlap}]} (살아 있는 서사만)."""
    meta = _live_meta(conn)
    out: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute("SELECT item_idx, narrative_topic, rule, doc_overlap FROM market_today_links WHERE mt_id=? "
                          "ORDER BY item_idx, rule, doc_overlap DESC, narrative_topic", (mt_id,)):
        m = meta.get(r["narrative_topic"])
        if m:
            out[r["item_idx"]].append({"topic": r["narrative_topic"], **m, "rule": r["rule"], "doc_overlap": r["doc_overlap"]})
    return out


# ---------- 빈도 · 갱신 앞당김 ----------

def frequency(conn, since: str | None = None) -> dict[str, dict]:
    """주제별 이번 주(월요일부터) 연결 화두 수·회차 수(마감 정리 제외) → {topic: {topics, sessions, keys}}."""
    ensure_schema(conn)
    since = since or week_start().isoformat()
    out: dict[str, dict] = {}
    for r in conn.execute(
            "SELECT l.narrative_topic t, l.mt_id, l.item_idx FROM market_today_links l JOIN market_today m ON m.id=l.mt_id "
            "WHERE m.trade_date >= ? AND m.slot != ?", (since, WRAP_SLOT)):
        f = out.setdefault(r["t"], {"keys": set(), "mts": set()})
        f["keys"].add((r["mt_id"], r["item_idx"]))
        f["mts"].add(r["mt_id"])
    return {t: {"topics": len(f["keys"]), "sessions": len(f["mts"]), "keys": f["keys"]} for t, f in out.items()}


def boosted_topics(conn, since: str | None = None) -> set[str]:
    """다음 갱신 앞당김(§9.3) — 이번 주 연결 회차 3회 이상 + 마지막 갱신 3일 넘게 지난 서사."""
    freq = frequency(conn, since)
    hot = [t for t, f in freq.items() if f["sessions"] >= BOOST_MIN_SESSIONS]
    if not hot:
        return set()
    q = ",".join("?" * len(hot))
    return {r[0] for r in conn.execute(
        f"SELECT topic FROM narratives WHERE topic IN ({q}) AND superseded_at IS NULL AND COALESCE(kind,'topic')='topic' "
        f"AND julianday('now') - julianday(created_at) > ?", (*hot, BOOST_STALE_DAYS))}


def strand_counts(conn, members: list[str], freq: dict | None = None, boosted: set | None = None) -> dict:
    """줄기(여러 서사 묶음)의 Market Today 연결 — 화두·회차를 서사끼리 겹치지 않게 센다."""
    freq = frequency(conn) if freq is None else freq
    boosted = boosted_topics(conn) if boosted is None else boosted
    keys = set().union(*(freq[m]["keys"] for m in members if m in freq)) if members else set()
    return {"mt_topics": len(keys), "mt_sessions": len({k[0] for k in keys}), "boost": any(m in boosted for m in members)}


# ---------- 타임라인 ----------

def timeline(conn, narrative_id: int, now: datetime | None = None) -> dict | None:
    """내러티브 상세 '장중 화두 타임라인' — 최근 2일 회차 격자 + 연결 화두 목록 + 집계.
    칸 상태: linked 연결 · unlinked 연결 없음 · scheduled 예정(아직 시각 전이거나 연결 계산 전) · absent 회차 없음(건너뜀)."""
    from pipeline.market_today import SLOTS, SLOT_LABEL, ensure_schema as mt_schema
    mt_schema(conn)
    ensure_schema(conn)
    row = conn.execute("SELECT topic FROM narratives WHERE id=?", (narrative_id,)).fetchone()
    if not row:
        return None
    topic = row["topic"]
    now = (now or datetime.now(timezone.utc)).astimezone(KST)
    today = now.date()
    first = conn.execute("SELECT MIN(trade_date) FROM market_today").fetchone()[0]
    dates = [r[0] for r in conn.execute("SELECT DISTINCT trade_date FROM market_today ORDER BY trade_date DESC LIMIT 2")]
    if first and today.weekday() < 5 and now.time() < SLOTS[-1][1] and (not dates or today.isoformat() > dates[0]):
        dates = [today.isoformat(), *dates][:2]   # 장중인데 오늘 회차가 아직 없으면 오늘 칸은 '예정'
    sessions = {(r["trade_date"], r["slot"]): r for r in conn.execute(
        f"SELECT id, trade_date, slot, links_at FROM market_today WHERE trade_date IN ({','.join('?' * len(dates))})",
        dates)} if dates else {}
    linked = {r[0] for r in conn.execute("SELECT DISTINCT mt_id FROM market_today_links WHERE narrative_topic=?", (topic,))}
    new_keys = [s for s, _ in SLOTS]
    days = []
    for d in dates:
        have = sorted(s for (dd, s) in sessions if dd == d)
        keys = have if have and not set(have) & set(new_keys) else new_keys   # 옛 회차(10:00·13:00·15:40)만 있는 날은 그 회차로
        cells = []
        for s in keys:
            r = sessions.get((d, s))
            if r is None:
                t = dict(SLOTS).get(s)
                later = d > today.isoformat() or (d == today.isoformat() and t is not None and now.time() < t)
                state = "scheduled" if later else "absent"
            elif r["links_at"] is None:
                state = "scheduled"
            else:
                state = "linked" if r["id"] in linked else "unlinked"
            cells.append({"slot": s, "label": SLOT_LABEL.get(s, s), "state": state, "wrap": s == WRAP_SLOT})
        days.append({"trade_date": d, "cells": cells})
    items = []
    for r in conn.execute(
            "SELECT m.id mt_id, m.trade_date, m.slot, m.items_json, l.item_idx, l.rule, l.doc_overlap "
            "FROM market_today_links l JOIN market_today m ON m.id=l.mt_id WHERE l.narrative_topic=? "
            "ORDER BY m.trade_date DESC, m.slot DESC, l.item_idx LIMIT 30", (topic,)):
        its = json.loads(r["items_json"] or "[]")
        title = its[r["item_idx"]]["title"] if r["item_idx"] < len(its) else ""
        items.append({"mt_id": r["mt_id"], "trade_date": r["trade_date"], "slot": r["slot"],
                      "label": SLOT_LABEL.get(r["slot"], r["slot"]), "title": title, "rule": r["rule"],
                      "doc_overlap": r["doc_overlap"], "wrap": r["slot"] == WRAP_SLOT})
    f = frequency(conn, week_start(today).isoformat()).get(topic, {"topics": 0, "sessions": 0})
    return {"topic": topic, "narrative_id": narrative_id, "collected_since": first, "days": days, "items": items,
            "week_topics": f["topics"], "week_sessions": f["sessions"],
            "boost": topic in boosted_topics(conn, week_start(today).isoformat())}


# ---------- 후보 ----------

def _window_items(conn, today: date) -> list[dict]:
    since = (today - timedelta(days=CANDIDATE_DAYS)).isoformat()
    out = []
    for r in conn.execute("SELECT id, trade_date, slot, items_json, sources_json FROM market_today "
                          "WHERE trade_date >= ? AND trade_date <= ? AND slot != ? ORDER BY trade_date, slot",
                          (since, today.isoformat(), WRAP_SLOT)):
        sources = json.loads(r["sources_json"] or "{}")
        for idx, it in enumerate(json.loads(r["items_json"] or "[]")):
            srcs = [sources[x] for x in it.get("refs") or [] if x in sources]
            out.append({"mt_id": r["id"], "trade_date": r["trade_date"], "slot": r["slot"], "idx": idx,
                        "title": it.get("title") or "", "tags": [t for t in it.get("tags") or [] if norm(t)],
                        "docs": [int(s["doc_id"]) for s in srcs if s.get("doc_id")],
                        "source_keys": [str(s.get("doc_id") or s.get("url") or s.get("title")) for s in srcs]})
    return out


def group_items(items: list[dict], excluded: set[str]) -> list[list[dict]]:
    """공유 태그로 이어진 화두 묶음(제외 태그 = 살아 있는 서사 이름·일반어는 고리로 쓰지 않는다)."""
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    first_by_tag: dict[str, int] = {}
    for i, it in enumerate(items):
        for t in {norm(x) for x in it["tags"]} - excluded:
            if t in first_by_tag:
                parent[find(i)] = find(first_by_tag[t])
            else:
                first_by_tag[t] = i
    groups: dict[int, list[dict]] = defaultdict(list)
    for i, it in enumerate(items):
        if {norm(x) for x in it["tags"]} - excluded:
            groups[find(i)].append(it)
    return list(groups.values())


def _merge_target(conn, docs: set[int], first_seen: str) -> dict | None:
    """후보 출처가 같은 기간에 새로 생긴 서사의 근거(그 주제에 연결된 문서)와 2건 이상 겹치면 합칠 서사."""
    if not docs:
        return None
    since = (date.fromisoformat(first_seen) - timedelta(days=MERGE_NEW_DAYS)).isoformat()
    new_topics = [r[0] for r in conn.execute(
        "SELECT topic FROM narratives WHERE COALESCE(kind,'topic')='topic' GROUP BY topic "
        "HAVING MIN(created_at) >= ? AND SUM(superseded_at IS NULL) > 0", (since,))]
    if not new_topics:
        return None
    names = _doc_topic_names(conn, docs)
    best = None
    for t in new_topics:
        ov = sum(1 for d in docs if t in names.get(d, set()))
        if ov >= MERGE_MIN_OVERLAP and (best is None or ov > best["overlap"]):
            best = {"topic": t, "overlap": ov}
    return best


def refresh_candidates(conn, today: date | None = None) -> dict:
    """창 안 화두 묶음으로 후보·관찰 중을 다시 계산한다. 승인·무시(기간 안) 행은 상태를 지킨다."""
    ensure_schema(conn)
    today = today or _today_kst()
    live = {norm(t) for t in _live_topics(conn)}
    aliases = set(_aliases(conn))
    excluded = live | aliases | {norm(t) for t in GENERIC_TAGS}
    held: dict[str, dict] = {}
    for r in conn.execute("SELECT tag, status, dismissed_until, detail_json FROM narrative_candidates "
                          "WHERE status IN ('approved','dismissed')"):
        if r["status"] == "dismissed" and (r["dismissed_until"] or "") < today.isoformat():
            continue
        for t in [r["tag"], *(json.loads(r["detail_json"] or "{}").get("tags") or [])]:
            held[norm(t)] = {"tag": r["tag"], "status": r["status"]}
    items = _window_items(conn, today)
    linked: dict[tuple, list[str]] = defaultdict(list)
    for r in conn.execute("SELECT mt_id, item_idx, narrative_topic FROM market_today_links"):
        linked[(r[0], r[1])].append(r[2])
    seen, counts = set(), Counter()
    for g in group_items(items, excluded):
        sessions = sorted({(it["trade_date"], it["slot"], it["mt_id"]) for it in g})
        days = sorted({s[0] for s in sessions})
        if len(sessions) < CANDIDATE_MIN_SESSIONS:
            continue
        status = "pending" if len(days) >= CANDIDATE_MIN_DAYS else "watching"
        tag_count: Counter = Counter()
        first_pos: dict[str, tuple[int, int]] = {}
        display: dict[str, Counter] = defaultdict(Counter)
        for pos, it in enumerate(g):
            for k, t in enumerate(it["tags"]):
                nt = norm(t)
                if nt in excluded:
                    continue
                tag_count[nt] += 1
                first_pos.setdefault(nt, (pos, k))
                display[nt][t.strip()] += 1
        ranked = sorted(tag_count, key=lambda t: (-tag_count[t], first_pos[t], t))
        top = [t for t in ranked if tag_count[t] == tag_count[ranked[0]]][:2]
        key = ranked[0]
        hold = next((held[t] for t in ranked if t in held), None)
        if hold:   # 이미 승인했거나 무시 기간 안 — 그 행을 덮지 않는다
            seen.add(hold["tag"])
            continue
        docs = {d for it in g for d in it["docs"]}
        detail = {
            "days": len(days), "sessions": len(sessions),
            "sources": len({k for it in g for k in it["source_keys"]}),
            "tags": [display[t].most_common(1)[0][0] for t in ranked],
            "items": [{"mt_id": it["mt_id"], "trade_date": it["trade_date"], "slot": it["slot"], "title": it["title"]} for it in g],
            "linked": sorted({t for it in g for t in linked.get((it["mt_id"], it["idx"]), [])}),
            "merge_into": _merge_target(conn, docs, days[0]) if status == "pending" else None,
        }
        name = " · ".join(display[t].most_common(1)[0][0] for t in top)
        conn.execute(
            "INSERT INTO narrative_candidates (tag, name, first_seen, last_seen, sessions_json, detail_json, status, updated_at) "
            "VALUES (?,?,?,?,?,?,?, datetime('now')) ON CONFLICT(tag) DO UPDATE SET name=excluded.name, "
            "first_seen=excluded.first_seen, last_seen=excluded.last_seen, sessions_json=excluded.sessions_json, "
            "detail_json=excluded.detail_json, status=excluded.status, dismissed_until=NULL, narrative_topic=NULL, "
            "updated_at=excluded.updated_at",
            (key, name, days[0], days[-1],
             json.dumps([{"mt_id": s[2], "trade_date": s[0], "slot": s[1]} for s in sessions]),
             json.dumps(detail, ensure_ascii=False), status))
        seen.add(key)
        counts[status] += 1
    # 더는 조건을 채우지 않는 후보·관찰 중, 기간이 끝난 무시는 지운다(승인 행은 남김)
    stale = [r[0] for r in conn.execute(
        "SELECT tag FROM narrative_candidates WHERE (status IN ('pending','watching') OR "
        "(status='dismissed' AND COALESCE(dismissed_until,'') < ?))", (today.isoformat(),)) if r[0] not in seen]
    for t in stale:
        conn.execute("DELETE FROM narrative_candidates WHERE tag=?", (t,))
    return {"pending": counts["pending"], "watching": counts["watching"], "removed": len(stale)}


def list_candidates(conn) -> list[dict]:
    """후보 카드 — 후보 · 승인 뒤 첫 버전 대기 · 관찰 중."""
    from pipeline.market_today import SLOT_LABEL
    ensure_schema(conn)
    live = set(_live_topics(conn))
    meta = _live_meta(conn)
    out = []
    for r in conn.execute("SELECT * FROM narrative_candidates WHERE status IN ('pending','watching','approved')"):
        d = json.loads(r["detail_json"] or "{}")
        if r["status"] == "approved" and (d.get("mode") == "merge" or r["narrative_topic"] in live):
            continue   # 합쳤거나 첫 버전이 나왔으면 카드에서 내린다
        merge = d.get("merge_into")
        if merge and merge["topic"] in meta:
            merge = {**merge, **meta[merge["topic"]]}
        elif merge:
            merge = None
        sess = json.loads(r["sessions_json"] or "[]")
        out.append({"tag": r["tag"], "name": r["name"], "status": r["status"], "first_seen": r["first_seen"],
                    "last_seen": r["last_seen"], "days": d.get("days", 0), "sessions": d.get("sessions", 0),
                    "sources": d.get("sources", 0), "tags": d.get("tags", []),
                    "session_list": [{**s, "label": SLOT_LABEL.get(s["slot"], s["slot"])} for s in sess],
                    "titles": list(dict.fromkeys(i["title"] for i in d.get("items", []))),
                    "linked": d.get("linked", []), "merge_into": merge,
                    "narrative_topic": r["narrative_topic"], "attempt": d.get("attempt")})
    order = {"pending": 0, "approved": 1, "watching": 2}
    out.sort(key=lambda x: (order[x["status"]], -x["sessions"], -x["sources"], x["tag"]))
    return out


def approve(conn, tag: str) -> dict | None:
    """[서사로 만들기] / [○○에 합치기] — 생성은 하지 않는다. 새 주제는 다음 내러티브 갱신 때 첫 버전,
    합치기는 그 태그를 합칠 서사와 태그 일치로 보고 후보 회차를 다시 연결한다(결정적)."""
    ensure_schema(conn)
    r = conn.execute("SELECT * FROM narrative_candidates WHERE tag=?", (tag,)).fetchone()
    if not r or r["status"] != "pending":
        return None
    d = json.loads(r["detail_json"] or "{}")
    merge = d.get("merge_into")
    if merge:
        d.update(mode="merge", alias_tags=d.get("tags", [])[:2])
        topic = merge["topic"]
    else:
        d.update(mode="new")
        topic = (d.get("tags") or [r["name"]])[0]
    conn.execute("UPDATE narrative_candidates SET status='approved', narrative_topic=?, detail_json=?, updated_at=datetime('now') "
                 "WHERE tag=?", (topic, json.dumps(d, ensure_ascii=False), tag))
    if merge:
        for s in json.loads(r["sessions_json"] or "[]"):
            link_narratives(conn, s["mt_id"])
    conn.commit()
    return {"tag": tag, "status": "approved", "mode": d["mode"], "narrative_topic": topic, "dismissed_until": None}


def dismiss(conn, tag: str, today: date | None = None) -> dict | None:
    """[무시] — 그 묶음의 태그는 14일 동안 다시 후보로 올리지 않는다."""
    ensure_schema(conn)
    r = conn.execute("SELECT status FROM narrative_candidates WHERE tag=?", (tag,)).fetchone()
    if not r or r["status"] not in ("pending", "watching"):
        return None
    until = ((today or _today_kst()) + timedelta(days=DISMISS_DAYS)).isoformat()
    conn.execute("UPDATE narrative_candidates SET status='dismissed', dismissed_until=?, updated_at=datetime('now') WHERE tag=?",
                 (until, tag))
    conn.commit()
    return {"tag": tag, "status": "dismissed", "mode": None, "narrative_topic": None, "dismissed_until": until}


def pending_new_topics(conn) -> list[str]:
    """승인했지만 아직 첫 버전이 없는 새 주제 — 다음 내러티브 갱신이 집어 간다."""
    ensure_schema(conn)
    live = set(_live_topics(conn))
    out = []
    for r in conn.execute("SELECT narrative_topic, detail_json FROM narrative_candidates WHERE status='approved' "
                          "AND narrative_topic IS NOT NULL ORDER BY updated_at"):
        if json.loads(r[1] or "{}").get("mode") == "new" and r[0] not in live:
            out.append(r[0])
    return out


def record_attempt(conn, topic: str, status: str) -> None:
    """승인 주제의 첫 버전 시도 결과(fresh·empty·not_found…) — 카드가 '재료 부족'을 보일 수 있게."""
    for r in conn.execute("SELECT tag, detail_json FROM narrative_candidates WHERE status='approved' AND narrative_topic=?",
                          (topic,)).fetchall():
        d = json.loads(r[1] or "{}")
        d["attempt"] = status
        conn.execute("UPDATE narrative_candidates SET detail_json=? WHERE tag=?", (json.dumps(d, ensure_ascii=False), r[0]))
    conn.commit()
