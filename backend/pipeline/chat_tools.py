"""대화 도구 카탈로그 — 전부 읽기 전용·LLM 0 (docs/specs/chat-agent.md §2, D-131).

각 도구는 기존 라우터/파이프라인 로직의 얇은 래퍼다. 반환은 근거(evidence) 목록:
  {"kind": doc|narrative|edges|knowledge|question|lens|quote|regime|briefing|digest|signal|action|youtube,
   "title": str, "text": str, "date": str|None, "doc_id": int|None, "href": str|None}
종합 단계가 이 목록에 [1..N] 번호를 붙이고, 인용은 href로 링크된다.

설계 규칙(Anthropic ACI): 이름=용도, 겹치는 도구 없음, 엔티티는 이름으로 받고 코드가 해석,
실패는 빈 목록 + note로 돌려 종합이 "찾지 못했다"고 말할 수 있게 한다.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from database import get_connection

DOC_CHARS = 1200
BODY_CHARS = 1500
ITEM_CHARS = 300


@dataclass
class ToolResult:
    name: str
    args: dict
    items: list[dict] = field(default_factory=list)
    note: str | None = None      # 실패·빈 결과 사유 (종합 프롬프트에 그대로 전달)


# ── 엔티티 해석 ───────────────────────────────────────────────────────────────

_KIND_ORDER = {"company": 0, "sector": 1, "theme": 2, "person": 3, "macro": 4, "policy": 5, "event": 6}


def resolve_entity(conn, name: str, prefer: tuple[str, ...] = ()):
    """이름 → entities 행. 정식명 → 종목코드/별칭 → 활성 키워드 → 전방일치. 회사 우선."""
    q = (name or "").strip()
    if not q:
        return None
    rows = conn.execute("SELECT id, type, name, aliases FROM entities WHERE name=?", (q,)).fetchall()
    if not rows:
        rows = conn.execute("SELECT id, type, name, aliases FROM entities WHERE aliases=?", (q,)).fetchall()
    if not rows:
        rows = conn.execute("""
            SELECT e.id, e.type, e.name, e.aliases FROM entity_keywords ek JOIN entities e ON e.id=ek.entity_id
            WHERE ek.keyword=? AND (ek.status='active' OR ek.status IS NULL)""", (q,)).fetchall()
    if not rows and len(q) >= 2:
        rows = conn.execute(
            "SELECT id, type, name, aliases FROM entities WHERE name LIKE ? || '%' ORDER BY length(name) LIMIT 8",
            (q,)).fetchall()
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: (0 if r["type"] in prefer else 1, _KIND_ORDER.get(r["type"], 9)))
    return rows[0]


def _company_code(conn, name: str) -> tuple[str | None, str | None]:
    ent = resolve_entity(conn, name, prefer=("company",))
    if ent and ent["type"] == "company" and ent["aliases"]:
        return ent["aliases"], ent["name"]
    return None, ent["name"] if ent else None


def _match_channels(conn, channel: str):
    """구독 유튜브 채널 매칭 — 공백 무시 부분일치, 실패 시 토큰(≥2자) 하나라도 포함."""
    rows = conn.execute("SELECT channel_id, title, handle FROM youtube_channels").fetchall()
    key = (channel or "").replace(" ", "").lower()
    if not key:
        return []
    def norm(r):
        return ((r["title"] or "") + " " + (r["handle"] or "")).replace(" ", "").lower()
    hit = [r for r in rows if key in norm(r) or norm(r).split("@")[0] and norm(r).split("@")[0] in key]
    if hit:
        return hit
    toks = [t.lower() for t in channel.split() if len(t) >= 2]
    return [r for r in rows if any(t in norm(r) for t in toks)]


def _mention_sentences(body: str, name: str, k: int = 2, width: int = 160) -> list[str]:
    """본문에서 엔티티가 언급된 문장 k개 (앞뒤 문맥 포함, width자)."""
    out = []
    last_end = -1
    for m in re.finditer(re.escape(name), body):
        if m.start() < last_end:          # 직전 창과 겹치는 언급은 건너뛴다 (같은 문장 중복 방지)
            continue
        last_end = m.start() + width // 2
        st = max(0, m.start() - width // 2)
        seg = body[st:st + width].replace("\n", " ").strip()
        # 문장 경계로 다듬기
        cut = re.search(r"[.!?。]\s", seg)
        if cut and cut.end() < width // 3:
            seg = seg[cut.end():]
        if seg and not any(seg in o or o in seg for o in out):
            out.append(seg)
        if len(out) >= k:
            break
    return out

# ── 도구 구현 ─────────────────────────────────────────────────────────────────

def search_docs(query: str, since_days: int | None = None, source: str | None = None,
                entity: str | None = None, k: int = 12) -> ToolResult:
    """수집 문서 하이브리드 검색(BM25+벡터) + 기간·소스·엔티티 필터."""
    from pipeline.rag import retrieve_docs
    args = {"query": query, "since_days": since_days, "source": source, "entity": entity}
    conn = get_connection()
    eid = None
    if entity:
        ent = resolve_entity(conn, entity)
        eid = ent["id"] if ent else None
    conn.close()
    docs = retrieve_docs(query, k=k, since_days=since_days, source=source, entity_id=eid)
    note = None
    if not docs and source:
        # 벡터·BM25 후보 풀에 해당 소스가 없을 수 있다(예: 유튜브 498건 vs 전체 16K) — 제목·본문 부분일치 폴백
        toks = [t for t in re.split(r"[^0-9A-Za-z가-힣]+", query) if len(t) >= 2][:3]
        if toks:
            conn = get_connection()
            # 1차: 토큰 전부 포함(AND) → 2차: 가장 긴 토큰(고유명사일 확률)만
            for attempt in (toks, [max(toks, key=len)]):
                cond = " AND ".join("(title LIKE '%'||?||'%' OR markdown LIKE '%'||?||'%')" for _ in attempt)
                params = [x for t in attempt for x in (t, t)]
                rows = conn.execute(f"""
                    SELECT id, source_type, title, published_at, substr(markdown,1,{DOC_CHARS}) excerpt
                    FROM raw_documents WHERE source_type=? AND {cond} ORDER BY published_at DESC LIMIT ?""",
                    (source, *params, k)).fetchall()
                if rows:
                    docs = [dict(r) for r in rows]
                    note = f"의미 검색에 없어 {source} 문서 제목·본문 부분일치('{' '.join(attempt)}')로 찾음"
                    break
            conn.close()
    items = [{"kind": "doc", "title": d["title"], "text": d["excerpt"] or "",
              "date": (d["published_at"] or "")[:10], "doc_id": d["id"], "href": f"/doc/{d['id']}",
              "source_type": d["source_type"]} for d in docs]
    return ToolResult("search_docs", args, items, note if items else "검색 결과 없음")


def open_doc(doc_id: int) -> ToolResult:
    """문서 1건 전문(앞 4,000자) — 인용 문서를 더 자세히 볼 때."""
    conn = get_connection()
    r = conn.execute("SELECT id, source_type, title, published_at, substr(markdown,1,4000) body "
                     "FROM raw_documents WHERE id=?", (doc_id,)).fetchone()
    conn.close()
    if not r:
        return ToolResult("open_doc", {"doc_id": doc_id}, [], f"문서 {doc_id} 없음")
    return ToolResult("open_doc", {"doc_id": doc_id}, [{
        "kind": "doc", "title": r["title"], "text": r["body"] or "", "date": (r["published_at"] or "")[:10],
        "doc_id": r["id"], "href": f"/doc/{r['id']}", "source_type": r["source_type"]}])


def list_recent(kind: str, entity: str | None = None, channel: str | None = None, n: int = 8,
                days: int | None = None) -> ToolResult:
    """시스템 산출물·수집물의 최신 목록 — 문서 검색이 아니라 테이블 조회. kind=docs는 최근 N일 유입 문서(제목+요약)."""
    args = {"kind": kind, "entity": entity, "channel": channel, "n": n, "days": days}
    n = max(1, min(int(n or 8), 20))
    conn = get_connection()
    try:
        if kind == "docs":
            d = max(1, min(int(days or 1), 30))
            where, params = ["rd.published_at >= datetime('now', ?)", "length(rd.markdown) >= 80"], [f"-{d} days"]
            if entity:
                ent = resolve_entity(conn, entity)
                if ent:
                    where.append("(rd.id IN (SELECT doc_id FROM entity_links WHERE entity_id=?) OR rd.title LIKE '%'||?||'%' OR rd.markdown LIKE '%'||?||'%')")
                    params += [ent["id"], ent["name"], ent["name"]]
            rows = conn.execute(f"""
                SELECT rd.id, rd.source_type, rd.title, rd.published_at, e.summary,
                       substr(rd.markdown,1,{ITEM_CHARS}) ex, substr(rd.markdown,1,20000) body
                FROM raw_documents rd LEFT JOIN enrichments e ON e.doc_id=rd.id
                WHERE {' AND '.join(where)} ORDER BY rd.published_at DESC LIMIT ?""", (*params, n)).fetchall()
            ent_name = ent["name"] if (entity and ent) else None
            items = []
            for r in rows:
                text = (r["summary"] or r["ex"] or "")[:ITEM_CHARS]
                if ent_name:
                    # 시황·리서치처럼 여러 종목을 다루는 문서는 요약에 이 종목이 없을 수 있다 — 언급 문장을 직접 붙인다
                    ments = _mention_sentences(r["body"] or "", ent_name, k=2)
                    if ments:
                        text += "\n언급: " + " / ".join(ments)
                items.append({"kind": "doc", "title": r["title"], "text": text[:ITEM_CHARS + 360],
                              "date": (r["published_at"] or "")[:10], "doc_id": r["id"], "href": f"/doc/{r['id']}",
                              "source_type": r["source_type"]})
            return ToolResult("list_recent", args, items, None if items else f"최근 {d}일 유입 문서 없음")

        if kind == "narratives":
            from pipeline.narrative import list_narratives
            items = []
            for r in list_narratives(conn)[:n]:
                text = " · ".join(x for x in [r.get("summary"), r.get("drift_summary")] if x)
                items.append({"kind": "narrative", "title": r["title"], "text": text[:ITEM_CHARS],
                              "date": (r.get("created_at") or "")[:10], "doc_id": None,
                              "href": f"/narrative?topic={r['topic']}"})
            return ToolResult("list_recent", args, items, None if items else "생성된 내러티브 없음")

        if kind == "digests":
            if not entity:
                return ToolResult("list_recent", args, [], "digests에는 entity(종목)가 필요")
            code, name = _company_code(conn, entity)
            if not code:
                return ToolResult("list_recent", args, [], f"'{entity}' 종목을 찾지 못함")
            rows = conn.execute("""
                SELECT d.period, d.period_start, d.digest, d.insights FROM entity_digests d
                JOIN entities e ON e.id=d.entity_id WHERE e.aliases=? ORDER BY d.period_start DESC LIMIT ?""",
                (code, n)).fetchall()
            items = [{"kind": "digest", "title": f"{name} {r['period'].upper()} 요약 {r['period_start']}",
                      "text": ((r["insights"] or "") + "\n" + (r["digest"] or ""))[:BODY_CHARS],
                      "date": r["period_start"], "doc_id": None, "href": f"/analyze/{code}/summary"} for r in rows]
            return ToolResult("list_recent", args, items, None if items else "다이제스트 없음")

        if kind == "youtube":
            where, params = ["rd.source_type='youtube'"], []
            if channel:
                chs = _match_channels(conn, channel)
                if not chs:
                    return ToolResult("list_recent", args, [], f"'{channel}' 유튜브 채널이 구독 목록에 없음 (피드 사이드바에서 채널을 등록해야 수집됨)")
                where.append("(" + " OR ".join("rd.source_id LIKE ?||'/%'" for _ in chs) + ")")
                params += [c["channel_id"] for c in chs]
            rows = conn.execute(f"""
                SELECT rd.id, rd.title, rd.published_at, rd.source_id, substr(rd.markdown,1,{ITEM_CHARS}) ex
                FROM raw_documents rd WHERE {' AND '.join(where)} ORDER BY rd.published_at DESC LIMIT ?""",
                (*params, n)).fetchall()
            ch_title = {c["channel_id"]: c["title"] for c in conn.execute("SELECT channel_id, title FROM youtube_channels")}
            items = [{"kind": "youtube", "title": r["title"],
                      "text": f"채널: {ch_title.get((r['source_id'] or '').split('/')[0], '?')}\n{r['ex'] or ''}",
                      "date": (r["published_at"] or "")[:10], "doc_id": r["id"], "href": f"/doc/{r['id']}"} for r in rows]
            return ToolResult("list_recent", args, items, None if items else "유튜브 문서 없음")

        if kind == "signals":
            where, params = ["s.date >= ?"], [(date.today() - timedelta(days=14)).isoformat()]
            if entity:
                ent = resolve_entity(conn, entity)
                if ent:
                    where.append("s.entity_id=?")
                    params.append(ent["id"])
            rows = conn.execute(f"""
                SELECT s.signal_type, s.date, s.payload_json, s.interpretation, e.name
                FROM signals s JOIN entities e ON e.id=s.entity_id WHERE {' AND '.join(where)}
                ORDER BY s.date DESC, s.id DESC LIMIT ?""", (*params, n)).fetchall()
            items = []
            for r in rows:
                p = json.loads(r["payload_json"] or "{}")
                brief = {k: v for k, v in p.items() if k != "docs"}
                items.append({"kind": "signal", "title": f"{r['name']} · {r['signal_type']} · {r['date']}",
                              "text": ((r["interpretation"] or "") + " " + json.dumps(brief, ensure_ascii=False))[:ITEM_CHARS],
                              "date": r["date"], "doc_id": None, "href": "/explore?list=signals"})
            return ToolResult("list_recent", args, items, None if items else "최근 14일 신호 없음")

        if kind == "actions":
            where, params = ["rcept_dt >= ?"], [(date.today() - timedelta(days=30)).strftime("%Y%m%d")]
            if entity:
                code, name = _company_code(conn, entity)
                if code:
                    where.append("stock_code=?")
                    params.append(code)
                elif name:
                    where.append("corp_name LIKE '%'||?||'%'")
                    params.append(name)
            rows = conn.execute(f"SELECT corp_name, action_type, report_nm, rcept_dt, summary FROM corporate_actions "
                                f"WHERE {' AND '.join(where)} ORDER BY rcept_dt DESC LIMIT ?", (*params, n)).fetchall()
            items = [{"kind": "action", "title": f"{r['corp_name']} · {r['action_type']} · {r['rcept_dt']}",
                      "text": (r["summary"] or r["report_nm"] or "")[:ITEM_CHARS], "date": r["rcept_dt"],
                      "doc_id": None, "href": "/actions"} for r in rows]
            return ToolResult("list_recent", args, items, None if items else "최근 30일 기업활동 없음")

        return ToolResult("list_recent", args, [], f"알 수 없는 kind '{kind}'")
    finally:
        conn.close()


def get_price_history(stock: str, days: int = 10) -> ToolResult:
    """일별 시세(종가·등락·거래량) 최근 N거래일 — '추이·이번주·지난달' 질문에. 실시간 시세(get_quote)와 짝."""
    days = max(2, min(int(days or 10), 60))
    conn = get_connection()
    try:
        code, name = _company_code(conn, stock)
        if not code:
            return ToolResult("get_price_history", {"stock": stock, "days": days}, [], f"'{stock}' 종목을 찾지 못함")
        rows = conn.execute("""
            SELECT trade_date, open, high, low, close, volume, fetched_at FROM stock_prices
            WHERE stock_code=? ORDER BY trade_date DESC LIMIT ?""", (code, days + 1)).fetchall()[::-1]
    finally:
        conn.close()
    if len(rows) < 2:
        return ToolResult("get_price_history", {"stock": stock, "days": days}, [], f"{name} 일별 시세 없음")
    lines, prev = [], None
    for r in rows:
        chg = f"{(r['close'] / prev - 1) * 100:+.1f}%" if prev else "—"
        lines.append(f"{r['trade_date']} 종가 {r['close']:,.0f} ({chg}) 고 {r['high']:,.0f} 저 {r['low']:,.0f} 거래량 {r['volume']:,.0f}")
        prev = r["close"]
    first, last = rows[1]["close"], rows[-1]["close"]
    span = f"{rows[1]['trade_date']}→{rows[-1]['trade_date']} 누적 {(last / first - 1) * 100:+.1f}%"
    text = ("\n".join(lines[1:]) + f"\n기간 {span}\n"
            "※ 일별 종가는 장 마감 직후(16:10 KST) 스냅샷이라 공식 종가·거래량과 차이가 날 수 있다 — "
            "오늘 실시간 시세의 '전일 대비'로 직전 종가를 교차 확인할 것")
    return ToolResult("get_price_history", {"stock": stock, "days": days}, [{
        "kind": "prices", "title": f"{name} 일별 시세 최근 {len(rows) - 1}거래일", "text": text,
        "date": rows[-1]["trade_date"], "doc_id": None, "href": f"/analyze/{code}/summary"}])


def get_narrative(topic: str) -> ToolResult:
    """주제 내러티브(최신 버전) 본문."""
    from pipeline.narrative import cached_meta
    conn = get_connection()
    try:
        r = cached_meta(conn, topic)
        if r.get("status") != "cached":
            ent = resolve_entity(conn, topic, prefer=("theme", "sector"))
            if ent and ent["name"] != topic:
                r = cached_meta(conn, ent["name"])
                topic = ent["name"]
    finally:
        conn.close()
    if r.get("status") != "cached":
        return ToolResult("get_narrative", {"topic": topic}, [], f"'{topic}' 내러티브 미생성({r.get('status')})")
    return ToolResult("get_narrative", {"topic": topic}, [{
        "kind": "narrative", "title": r["title"], "text": (r["narrative"] or "")[:BODY_CHARS],
        "date": (r.get("created_at") or "")[:10], "doc_id": None, "href": f"/narrative?topic={topic}",
        "stale": r.get("stale")}])


def get_worldmodel(entity: str) -> ToolResult:
    """인과 그래프에서 이 노드의 위치 — 양방향 인과 엣지 + 걸린 내러티브."""
    conn = get_connection()
    try:
        ent = resolve_entity(conn, entity)
        if not ent:
            return ToolResult("get_worldmodel", {"entity": entity}, [], f"'{entity}' 엔티티 없음")
        eid = ent["id"]
        rows = conn.execute("""
            SELECT r.rel_type, r.effect_direction, r.confidence, r.mechanism, r.narrative_id,
                   s.name src, d.name dst
            FROM entity_relations r JOIN entities s ON s.id=r.src_id JOIN entities d ON d.id=r.dst_id
            WHERE r.epistemic_type='hypothesis' AND r.rel_type IN ('CAUSES','BENEFITS_FROM')
              AND (r.src_id=? OR r.dst_id=?) ORDER BY r.confidence DESC LIMIT 12""", (eid, eid)).fetchall()
        if not rows:
            return ToolResult("get_worldmodel", {"entity": entity}, [], f"'{ent['name']}'에 걸린 인과 엣지 없음")
        lines = []
        for r in rows:
            arrow = "→" if r["rel_type"] == "CAUSES" else "⇠수혜"
            d = {"positive": "+", "negative": "−", "mixed": "±"}.get(r["effect_direction"] or "", "?")
            conf = f"확신 {r['confidence']:.1f}" if r["confidence"] is not None else ""
            mech = f" — {r['mechanism'][:120]}" if r["mechanism"] else ""
            lines.append(f"- {r['src']} {arrow} {r['dst']} ({d}, {conf}){mech}")
        nids = [x for x in {r["narrative_id"] for r in rows} if x]
        nar = []
        if nids:
            ph = ",".join("?" * len(nids))
            nar = [f"{r['title']} (/narrative?topic={r['topic']})" for r in conn.execute(
                f"SELECT topic, title FROM narratives WHERE id IN ({ph}) GROUP BY topic", nids)]
        text = "\n".join(lines) + (("\n걸린 내러티브: " + " · ".join(nar)) if nar else "")
        return ToolResult("get_worldmodel", {"entity": entity}, [{
            "kind": "edges", "title": f"{ent['name']} 인과 엣지 {len(rows)}건 (전부 가설, 확신도 표기)",
            "text": text[:BODY_CHARS + 500], "date": None, "doc_id": None,
            "href": f"/knowledge/ontology?focus={eid}"}])
    finally:
        conn.close()


def get_knowledge(query: str, n: int = 6) -> ToolResult:
    """승격된 지식(검증된 전제) 중 질문과 의미 유사한 것."""
    from pipeline.knowledge_recall import recall_for_query
    conn = get_connection()
    note = None
    try:
        items_raw = recall_for_query(conn, query, limit=n)
        if not items_raw:
            # 질의가 짧거나 표현이 달라 유사도 문턱(0.45)에 못 미치면 문턱을 낮춰 후보를 보인다 — 종합이 관련성 판단
            items_raw = recall_for_query(conn, query, limit=min(n, 4), min_sim=0.30)
            if items_raw:
                note = "유사도 문턱을 낮춰 찾은 후보 — 질문과의 관련성은 답변에서 판단"
    finally:
        conn.close()
    hint = {"hypothesis": " (아직 가설)", "contested": " (이견 있음)"}
    layer = {"event": "사건", "flow": "흐름", "cycle": "사이클", "structure": "구조", "regime": "체제"}
    items = [{"kind": "knowledge", "title": f"지식 · {layer.get(k.get('pace_layer'), '')}층",
              "text": f"{k['statement']}{hint.get(k['epistemic_status'], '')}", "date": None,
              "doc_id": None, "href": "/knowledge"} for k in items_raw]
    return ToolResult("get_knowledge", {"query": query}, items, (note if items else "유사한 승격 지식 없음"))


def get_questions(entity: str | None = None, n: int = 6) -> ToolResult:
    """핵심질문 트래커의 미결 질문 + 2층 판정."""
    from pipeline.questions import list_questions
    qs = list_questions()
    if entity:
        key = entity.strip()
        qs = [q for q in qs if key and key in (q.get("text") or "")]
    qs = qs[:n]
    items = [{"kind": "question", "title": (q["text"] or "")[:80],
              "text": f"상태 {q.get('status')} · 선행 {q.get('lead_verdict') or '-'} · 확인 {q.get('confirm_verdict') or '-'}"
                      f"{' · 괴리' if q.get('divergence') else ''}\n{(q.get('verdict_summary') or '')[:ITEM_CHARS]}",
              "date": (q.get("updated_at") or "")[:10], "doc_id": None, "href": f"/question/{q['id']}"} for q in qs]
    return ToolResult("get_questions", {"entity": entity}, items, None if items else "해당 질문 없음")


def get_lens(stock: str, lens_type: str | None = None) -> ToolResult:
    """투자 렌즈(가치·추세) 캐시 판독."""
    from pipeline.investor_lens import LENS_TYPES, peek
    conn = get_connection()
    code, name = _company_code(conn, stock)
    conn.close()
    if not code:
        return ToolResult("get_lens", {"stock": stock}, [], f"'{stock}' 종목을 찾지 못함")
    items = []
    for lt in LENS_TYPES:
        if lens_type and lt != lens_type:
            continue
        p = peek(code, lt, "kr")
        if not p or not p.get("body"):
            continue
        items.append({"kind": "lens", "title": f"{name} {'가치' if lt == 'value' else '추세'} 렌즈 · 판독 {p.get('stance') or '-'}"
                                                 + (" (재료 변경됨, 갱신 전)" if p.get("stale") else ""),
                      "text": (p["body"] or "")[:BODY_CHARS], "date": (p.get("created_at") or "")[:10],
                      "doc_id": None, "href": f"/analyze/{code}/lens"})
    return ToolResult("get_lens", {"stock": stock, "lens_type": lens_type}, items,
                      None if items else f"{name} 렌즈 판독 미생성")


def get_quote(stocks: list[str] | str) -> ToolResult:
    """질문 속 종목의 실시간 시세. 종목명은 resolve_entity로 해석(회사 우선) — 텍스트 부분일치는 '하이닉스'→'이닉스' 오탐."""
    from pipeline.quotes import fetch_quotes
    names = stocks if isinstance(stocks, list) else [stocks]
    conn = get_connection()
    try:
        resolved = []
        for nm in names:
            code, name = _company_code(conn, str(nm))
            if code:
                resolved.append((code, name))
    finally:
        conn.close()
    if not resolved:
        return ToolResult("get_quote", {"stocks": names}, [], "종목명을 해석하지 못함")
    quotes = {q["stock_code"]: q for q in fetch_quotes([c for c, _ in resolved])}
    lines = []
    for code, name in resolved:
        q = quotes.get(code)
        if not q or q.get("price") is None:
            continue
        status = "장중" if q.get("market_status") == "OPEN" else "마감"
        lines.append(f"- {name}({code}): {q['price']:,.0f}원 ({q['change_pct']:+.1f}%, 전일 대비 {q.get('change', 0):+,.0f}원) · {status} · {(q.get('traded_at') or '')[:16]}")
    if not lines:
        return ToolResult("get_quote", {"stocks": names}, [], "시세 조회 실패")
    return ToolResult("get_quote", {"stocks": names}, [{
        "kind": "quote", "title": "실시간 시세 (답변 시점)", "text": "\n".join(lines),
        "date": date.today().isoformat(), "doc_id": None, "href": None}])


def get_regime() -> ToolResult:
    """시장 국면(리스크 포스처) + 매크로·유동성 요약."""
    from pipeline.market_regime import get_regime as _regime
    items = []
    try:
        r = _regime()
        parts = []
        for mk, label in (("us", "미국"), ("kr", "한국")):
            m = r.get(mk)
            if m:
                parts.append(f"{label}: {m.get('posture')} — {m.get('reason')}")
        if parts:
            items.append({"kind": "regime", "title": f"시장 국면 (기준일 {r.get('as_of') or '-'})",
                          "text": "\n".join(parts), "date": r.get("as_of"), "doc_id": None, "href": "/home"})
    except Exception as e:  # noqa: BLE001
        return ToolResult("get_regime", {}, [], f"국면 조회 실패: {type(e).__name__}")
    try:
        from pipeline.macro import get_macro
        m = get_macro(with_signal=True)
        vals = [f"{it.get('label')}: {it.get('value')}" for it in (m.get("items") or [])[:8]]
        sig = m.get("signal") or {}
        sig_text = sig.get("text") or sig.get("summary") if isinstance(sig, dict) else None
        if vals or sig_text:
            items.append({"kind": "regime", "title": "매크로·유동성", "text": ((sig_text or "") + "\n" + " · ".join(vals))[:BODY_CHARS],
                          "date": None, "doc_id": None, "href": "/home"})
    except Exception:
        pass
    return ToolResult("get_regime", {}, items, None if items else "국면 스냅샷 없음")


def get_us_briefing(trade_date: str | None = None) -> ToolResult:
    """어젯밤 미국장 브리핑(저장분) — 지수·동인·섹터 쏠림·개별 이슈·스터디 후보."""
    conn = get_connection()
    try:
        r = None
        fallback = None
        if trade_date:
            r = conn.execute("SELECT trade_date, synthesis_json FROM us_briefings WHERE trade_date=?", (trade_date,)).fetchone()
        if not r:
            r = conn.execute("SELECT trade_date, synthesis_json FROM us_briefings ORDER BY trade_date DESC LIMIT 1").fetchone()
            if r and trade_date:
                fallback = f"{trade_date} 브리핑은 없어 최신({r['trade_date']})을 반환"
    finally:
        conn.close()
    if not r or not r["synthesis_json"]:
        return ToolResult("get_us_briefing", {"trade_date": trade_date}, [], "저장된 미국장 브리핑 없음")
    try:
        syn = json.loads(r["synthesis_json"])
    except ValueError:
        syn = {"raw": r["synthesis_json"]}
    parts = []
    for k, v in syn.items():
        if isinstance(v, str) and v.strip():
            parts.append(f"[{k}] {v.strip()}")
        elif isinstance(v, list) and v:
            parts.append(f"[{k}] " + " / ".join(json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else x for x in v[:6]))
    return ToolResult("get_us_briefing", {"trade_date": r["trade_date"]}, [{
        "kind": "briefing", "title": f"미국장 브리핑 {r['trade_date']}" + (" (요청일 없음 → 최신)" if fallback else ""),
        "text": "\n".join(parts)[:BODY_CHARS + 500],
        "date": r["trade_date"], "doc_id": None, "href": "/home"}], fallback)


# ── 레지스트리 (라우터 카탈로그 + 인자 화이트리스트) ──────────────────────────

TOOLS: dict[str, dict] = {
    "search_docs": {"fn": search_docs, "args": {"query", "since_days", "source", "entity"},
                    "desc": "수집 문서(텔레그램·블로그·유튜브·컨콜·뉴스) 의미+키워드 검색. 사건·의견·언급을 찾을 때. "
                            "args: query(독립형 검색어, 필수), since_days(7|30|90), source(telegram|blog|youtube|transcript|canon), entity(엔티티명)"},
    "open_doc": {"fn": open_doc, "args": {"doc_id"},
                 "desc": "특정 문서 전문. 사용자가 이전 답변의 인용 문서를 더 보자고 할 때. args: doc_id(정수)"},
    "list_recent": {"fn": list_recent, "args": {"kind", "entity", "channel", "n", "days"},
                    "desc": "최신 목록 조회(문서 검색 아님). kind=docs(최근 days일 유입 문서 제목+요약 — '오늘/이번주 무슨 일·이슈' 질문에 필수, entity로 좁힘 가능)|"
                            "narratives(생성된 내러티브)|digests(종목 1D/1W 요약, entity 필수)|youtube(구독 채널 영상, channel=채널명)|"
                            "signals(언급급증·신고가 등 신호)|actions(유무증·합병 등 기업활동). args: kind, entity, channel, n(≤20), days(docs용, 1~30)"},
    "get_narrative": {"fn": get_narrative, "args": {"topic"},
                      "desc": "주제(테마·섹터·매크로) 내러티브 본문 — '시장이 지금 이 주제를 어떻게 서술하나'. args: topic"},
    "get_worldmodel": {"fn": get_worldmodel, "args": {"entity"},
                       "desc": "인과 그래프에서 엔티티의 위치 — 원인·결과·수혜 엣지와 걸린 내러티브. 영향·파급·왜 질문에. args: entity"},
    "get_knowledge": {"fn": get_knowledge, "args": {"query"},
                      "desc": "반복 관측으로 승격된 지식(검증된 전제). 구조적 배경이 필요할 때. args: query"},
    "get_questions": {"fn": get_questions, "args": {"entity", "n"},
                      "desc": "핵심질문 트래커 — 미결 질문과 판정(선행/확인/괴리). args: entity(선택), n"},
    "get_lens": {"fn": get_lens, "args": {"stock", "lens_type"},
                 "desc": "종목의 투자 렌즈 판독(가치/추세). args: stock(종목명), lens_type(value|trend, 선택)"},
    "get_quote": {"fn": get_quote, "args": {"stocks"},
                  "desc": "종목 실시간 시세·등락(현재 1시점). 주가·오늘·지금 질문에 반드시. args: stocks(종목명 배열)"},
    "get_price_history": {"fn": get_price_history, "args": {"stock", "days"},
                          "desc": "종목 일별 시세 최근 N거래일(종가·등락·거래량·누적). '추이·이번주·지난 N일·왜 올랐/내렸' 질문에 반드시 get_quote와 함께. args: stock(종목명), days(2~60, 기본 10)"},
    "get_regime": {"fn": get_regime, "args": set(),
                   "desc": "시장 국면(미국·한국 리스크 포스처)과 매크로·유동성 요약. 장세·국면·거시 질문에. args 없음"},
    "get_us_briefing": {"fn": get_us_briefing, "args": {"trade_date"},
                        "desc": "어젯밤 미국장 브리핑(거래대금 상위·섹터 쏠림·개별 이슈). args: trade_date(YYYY-MM-DD, 선택=최신)"},
}

MAX_TOOLS = 4


def catalog_text() -> str:
    return "\n".join(f"- {name}: {spec['desc']}" for name, spec in TOOLS.items())


def validate_calls(calls: list) -> list[dict]:
    """라우터 출력 → 화이트리스트 검증(도구명·인자 키), 중복 제거, ≤MAX_TOOLS."""
    out, seen = [], set()
    for c in calls or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        spec = TOOLS.get(name)
        if not spec:
            continue
        args = {k: v for k, v in (c.get("args") or {}).items() if k in spec["args"] and v not in (None, "", [])}
        key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "args": args})
        if len(out) >= MAX_TOOLS:
            break
    return out


def run_tool(call: dict) -> ToolResult:
    spec = TOOLS[call["name"]]
    try:
        return spec["fn"](**call["args"])
    except TypeError as e:            # 필수 인자 누락 등
        return ToolResult(call["name"], call["args"], [], f"인자 오류: {str(e)[:80]}")
    except Exception as e:  # noqa: BLE001 — 도구 실패가 턴을 죽이면 안 된다
        return ToolResult(call["name"], call["args"], [], f"실행 실패: {type(e).__name__}: {str(e)[:80]}")
