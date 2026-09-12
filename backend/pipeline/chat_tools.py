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
from pipeline.visibility import unverified_sql

DOC_CHARS = 1200
BODY_CHARS = 1500
ITEM_CHARS = 300


@dataclass
class ToolResult:
    name: str
    args: dict
    items: list[dict] = field(default_factory=list)
    note: str | None = None      # 실패·빈 결과 사유 (종합 프롬프트에 그대로 전달)
    assumed: list[dict] = field(default_factory=list)   # 이름 해석 가정 {query, entity_id, name, code, note} — 종합이 첫 줄에 밝히고 갭(assumption)으로 남김


# ── 엔티티 해석 ───────────────────────────────────────────────────────────────

_KIND_ORDER = {"company": 0, "sector": 1, "theme": 2, "person": 3, "macro": 4, "policy": 5, "event": 6}


_ALIAS_SHAPE = re.compile(r"^[가-힣A-Za-z0-9&]{2,8}$")


def _fuzzy_company(conn, q: str, prefix_rows=None) -> tuple[dict | None, str | None]:
    """등록명에 없는 구어체·브랜드명·약칭을 회사로 결정적으로 추정 (LLM 0). 스레드 33 '삼양라면' 계기.

    후보: ① 공유 접두어(≥2자) 회사들('삼양라면' → 삼양*) ② 글자 순서 포함 약칭('하닉' → SK하이닉스, '삼전' → 삼성전자).
    판별: 접두어 나머지 토큰('라면')이 걸린 문서 수 → 없으면 최근 180일 언급량.
    1위가 3건↑이고 2위의 2배↑면 '가정'(note 동봉), 아니면 후보 목록을 돌려 종합이 되묻게 한다.
    반환 (row|None, note|None): row 있으면 가정 성립, row 없고 note 있으면 후보 모호, 둘 다 None이면 후보 없음.
    """
    if not _ALIAS_SHAPE.match(q):
        return None, None
    comps = conn.execute("SELECT id, type, name, aliases FROM entities WHERE type='company' "
                         "AND aliases IS NOT NULL AND aliases != ''").fetchall()
    cands: dict[int, object] = {}
    residual = ""
    if prefix_rows:
        for r in prefix_rows:
            cands[r["id"]] = r
    else:
        for plen in range(min(len(q) - 1, 6), 1, -1):
            pre = q[:plen]
            hit = [r for r in comps if r["name"].startswith(pre)]
            if hit:
                for r in hit:
                    cands[r["id"]] = r
                residual = q[plen:]
                break
    if not cands and len(q) <= 4:
        # 약칭(하닉·삼전)은 접두어 후보가 전혀 없을 때만 — '삼화'처럼 그 이름으로 시작하는 회사가 있으면 그 가족 안에서만 고른다
        pat = re.compile(".*".join(re.escape(ch) for ch in q))
        for r in comps:
            if len(r["name"]) <= 12 and pat.search(r["name"]):
                cands[r["id"]] = r
    if not cands:
        return None, None

    def score(eid: int) -> int:
        if len(residual) >= 2:
            try:
                return conn.execute("SELECT count(*) FROM entity_links l JOIN doc_fts f ON f.rowid=l.doc_id "
                                    "WHERE l.entity_id=? AND doc_fts MATCH ?", (eid, f'"{residual}"')).fetchone()[0]
            except Exception:  # noqa: BLE001 — FTS 구문 오류 등은 0점
                return 0
        return conn.execute("SELECT count(*) FROM entity_links l JOIN raw_documents rd ON rd.id=l.doc_id "
                            "WHERE l.entity_id=? AND rd.published_at >= date('now','-180 days')", (eid,)).fetchone()[0]

    if len(residual) == 1:
        # 공유 접두어 바로 뒤 한 글자가 다르다('비나인' vs 비나텍) — 닮은 게 아니라 다른 이름이라는 증거다.
        # 추정하지 않는다 (D-143, chatId=37에서 '비나인'을 비나텍으로 잘못 가정했다)
        return None, None
    ranked = sorted(((score(i), r) for i, r in cands.items()), key=lambda x: -x[0])
    if ranked[0][0] == 0 and len(residual) >= 2:
        # 나머지 토큰('시품' 같은 오탈자)이 어느 문서에도 없으면 언급량으로 다시 가른다
        residual = ""
        ranked = sorted(((score(i), r) for i, r in cands.items()), key=lambda x: -x[0])
    top_n, top = ranked[0]
    second_n = ranked[1][0] if len(ranked) > 1 else 0
    if top_n >= 3 and top_n >= 2 * second_n:
        basis = (f"'{residual}' 언급 문서 {top_n}건이 {top['name']}에 연결" if len(residual) >= 2
                 else f"최근 180일 언급 {top_n}건으로 후보 중 압도적")
        return dict(top), f"'{q}'은(는) 등록된 종목명이 아니라 {top['name']}({top['aliases']})으로 가정해 조회함 — {basis}"
    names = [r["name"] for _, r in ranked[:4]]
    return None, f"'{q}'에 해당하는 종목이 분명하지 않음 — 후보: {', '.join(names)}. 어느 것인지 확인 필요"


def resolve_entity_ex(conn, name: str, prefer: tuple[str, ...] = (), asm: dict | None = None):
    """이름 → entities 행. 정식명 → 종목코드/별칭 → 활성 키워드 → 전방일치(단일) → 회사 퍼지 추정. 회사 우선.

    asm(dict)을 주면 가정·모호 정보를 담아 돌려준다: asm["assumed"]=[{query, entity_id, name, code, note}], asm["ambiguous"]=note.
    퍼지 추정은 회사에만(테마·섹터 선호 호출은 제외)."""
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
    if rows:
        rows = sorted(rows, key=lambda r: (0 if r["type"] in prefer else 1, _KIND_ORDER.get(r["type"], 9)))
        return rows[0]
    prefix_rows = []
    if len(q) >= 2:
        prefix_rows = conn.execute(
            "SELECT id, type, name, aliases FROM entities WHERE name LIKE ? || '%' ORDER BY length(name) LIMIT 8",
            (q,)).fetchall()
    if len(prefix_rows) == 1:
        return prefix_rows[0]
    if prefer and "company" not in prefer:
        # 테마·섹터 조회 — 전방일치 여러 건이면 예전처럼 가장 짧은 이름, 퍼지 추정은 하지 않는다
        return prefix_rows[0] if prefix_rows else None
    company_prefix = [r for r in prefix_rows if r["type"] == "company"]
    row, note = _fuzzy_company(conn, q, prefix_rows=company_prefix or None)
    if row:
        if asm is not None:
            asm.setdefault("assumed", []).append({"query": q, "entity_id": row["id"], "name": row["name"],
                                                  "code": row["aliases"], "note": note})
        return row
    if note and asm is not None:
        asm["ambiguous"] = note
    if prefix_rows and not note:
        return prefix_rows[0]
    return None


def resolve_entity(conn, name: str, prefer: tuple[str, ...] = ()):
    """resolve_entity_ex의 가정 정보 없는 버전 (기억 갱신 등 메모만 필요 없는 호출용)."""
    return resolve_entity_ex(conn, name, prefer)


def _company_code(conn, name: str, asm: dict | None = None) -> tuple[str | None, str | None]:
    ent = resolve_entity_ex(conn, name, prefer=("company",), asm=asm)
    if ent and ent["type"] == "company" and ent["aliases"]:
        return ent["aliases"], ent["name"]
    return None, ent["name"] if ent else None


_GENERIC_ALIAS = {"동사", "미언급", "본주", "메모리", "반도체", "전자", "sk", "adr", "국내", "업체", "3사"}


def entity_terms(conn, ent) -> list[str]:
    """엔티티의 검색 별칭 — 정식명 + 활성 키워드(콤마·슬래시 분해, 괄호 제거) + 종목코드.
    다른 엔티티에도 걸린 토큰(범용어)·너무 짧은 것은 제외. BM25 `(별칭 OR…) AND (주제…)`용 (D-137)."""
    if not ent:
        return []
    terms = [ent["name"]]
    rows = conn.execute("SELECT keyword FROM entity_keywords WHERE entity_id=? AND (status='active' OR status IS NULL)",
                        (ent["id"],)).fetchall()
    cand = []
    for r in rows:
        for tok in re.split(r"[,/·]", re.sub(r"\([^)]*\)", " ", r["keyword"] or "")):
            tok = tok.strip().lstrip("$")
            if len(tok) >= 2 and tok.lower() not in _GENERIC_ALIAS and tok not in cand:
                cand.append(tok)
    if cand:
        ph = ",".join("?" * len(cand))
        shared = {r["keyword"] for r in conn.execute(
            f"SELECT keyword FROM entity_keywords WHERE keyword IN ({ph}) AND entity_id != ?", (*cand, ent["id"]))}
        cand = [c for c in cand if c not in shared]
    terms += cand
    if ent["type"] == "company" and ent["aliases"]:
        terms.append(ent["aliases"])   # 종목코드
    seen, out = set(), []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:10]


def _match_sources(conn, name: str) -> tuple[list[str], list, list[str]]:
    """채널·블로거·작성자 이름 → raw_documents 필터 조건(SQL 조각, 파라미터, **매칭된 소스 이름들**).

    이름 목록은 종합 모델에게 "이 결과가 누구 것인지" 알려주는 데 쓴다 (D-143) — 전엔 필터만 걸고
    출처를 안 실어 보내, 모델이 맞는 문서를 받고도 "작성자를 확인할 수 없다"고 거부했다(chatId=37).
    스크랩 문서는 원본 채널이 scrap_links에 있으므로 그 경로로도 매칭한다.
    """
    key = (name or "").replace(" ", "").lower()
    conds, params, names = [], [], []
    if not key:
        return conds, params, names
    for r in conn.execute("SELECT url, blog_name, author FROM blog_sources"):
        hay = ((r["blog_name"] or "") + (r["author"] or "") + (r["url"] or "")).replace(" ", "").lower()
        if key in hay:
            conds.append("(rd.source_type='blog' AND rd.url LIKE ?||'%')")
            params.append(r["url"])
            names.append(r["blog_name"] or r["url"])
    for r in conn.execute("SELECT channel_name, display_name FROM telegram_channels"):
        hay = ((r["display_name"] or "") + (r["channel_name"] or "")).replace(" ", "").lower()
        if key in hay:
            conds.append("(rd.source_type='telegram' AND rd.source_id LIKE ?||'/%')")
            params.append(r["channel_name"])
            names.append(r["display_name"] or r["channel_name"])
            # 그 채널이 스크랩 채널이면 확장된 원문 문서도 같은 출처다 (D-142)
            conds.append("(rd.source_type='scrap' AND rd.id IN (SELECT doc_id FROM scrap_links WHERE channel=?))")
            params.append(r["channel_name"])
    for r in _match_channels(conn, name):
        conds.append("(rd.source_type='youtube' AND rd.source_id LIKE ?||'/%')")
        params.append(r["channel_id"])
        names.append(r["title"] or r["channel_id"])
    return conds, params, names


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
                entity: str | None = None, k: int = 12, variants: list[str] | str | None = None,
                channel: str | None = None) -> ToolResult:
    """수집 문서 하이브리드 검색(BM25+벡터) + 기간·소스·엔티티·**채널** 필터 + 검색어 변형·엔티티 별칭 확장(D-137).

    channel: 특정 채널·블로거·유튜버 안에서만 찾는다 (D-143) — 전엔 인자가 없어 후속질문이
    "그 채널에서 가장 강하게 말한 종목"으로 잘 재작성되고도 전역 검색으로 새어나갔다(chatId=37)."""
    from pipeline.rag import retrieve_docs
    vlist = [v for v in (variants if isinstance(variants, list) else [variants] if variants else []) if isinstance(v, str) and v.strip()][:3]
    args = {"query": query, "since_days": since_days, "source": source, "entity": entity,
            "variants": vlist or None, "channel": channel}
    conn = get_connection()
    eid, terms = None, None
    asm: dict = {}
    allow: set[int] | None = None
    cnames: list[str] = []
    if entity:
        ent = resolve_entity_ex(conn, entity, asm=asm)
        if ent:
            eid = ent["id"]
            terms = entity_terms(conn, ent)
    if channel:
        conds, cparams, cnames = _match_sources(conn, channel)
        if not conds:
            conn.close()
            return ToolResult("search_docs", args, [], f"'{channel}' 채널·블로거를 구독 소스에서 찾지 못함")
        allow = {r[0] for r in conn.execute(
            f"SELECT rd.id FROM raw_documents rd WHERE {' OR '.join(conds)}", cparams)}
    conn.close()
    docs = retrieve_docs(query, k=k, since_days=since_days, source=source, entity_id=eid,
                         variants=vlist or None, entity_terms=terms, doc_ids=allow)
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
                    SELECT id, source_type, source_id, url, title, published_at, substr(markdown,1,{DOC_CHARS}) excerpt
                    FROM raw_documents WHERE source_type=? AND {cond} ORDER BY published_at DESC LIMIT ?""",
                    (source, *params, k)).fetchall()
                if rows:
                    docs = [dict(r) for r in rows]
                    note = f"의미 검색에 없어 {source} 문서 제목·본문 부분일치('{' '.join(attempt)}')로 찾음"
                    break
            conn.close()
    if not docs and allow:
        # 채널 범위인데 의미 검색이 빈손 — '가장 강하게 말한 종목'처럼 추상적 질문은 어떤 청크와도 안 맞는다.
        # 그 채널의 최근 글을 근거로 돌려주면 종합이 직접 읽고 판단한다 (D-143).
        conn = get_connection()
        ph = ",".join("?" for _ in allow)
        rows = conn.execute(f"""
            SELECT id, source_type, source_id, url, title, published_at, substr(markdown,1,{DOC_CHARS}) excerpt
            FROM raw_documents WHERE id IN ({ph}) ORDER BY published_at DESC LIMIT ?""",
            (*allow, k)).fetchall()
        conn.close()
        if rows:
            docs = [dict(r) for r in rows]
            note = "의미 검색에 걸린 대목이 없어 이 채널의 최근 글을 최신순으로 돌려줌"
    items = [{"kind": "doc", "title": d["title"], "text": d["excerpt"] or "",
              "date": (d["published_at"] or "")[:10], "doc_id": d["id"], "href": f"/doc/{d['id']}",
              "source_type": d["source_type"]} for d in docs]
    # 항목마다 출처를 붙인다 — 채널로 좁혔어도 모델은 그걸 모른다 (D-143)
    if items:
        from pipeline.sources import source_names
        conn = get_connection()
        srcs = source_names(conn, [{"id": d["id"], "source_type": d["source_type"],
                                    "source_id": d.get("source_id"), "url": d.get("url")} for d in docs])
        conn.close()
        for it, d in zip(items, docs):
            who = (srcs.get(d["id"]) or {}).get("name")
            if who:
                it["title"] = f"[{who}] {it['title'] or ''}"
    if items and cnames:
        note = (note or "") + f"('{channel}' → {', '.join(dict.fromkeys(cnames))} 범위 검색)"
    return ToolResult("search_docs", args, items, note if items else (asm.get("ambiguous") or "검색 결과 없음"),
                      assumed=asm.get("assumed", []))


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
    """(래퍼) 엔티티 이름 해석의 가정·모호 메모를 결과에 싣는다 — 본체는 _list_recent."""
    asm: dict = {}
    res = _list_recent(kind=kind, entity=entity, channel=channel, n=n, days=days, asm=asm)
    res.assumed = asm.get("assumed", [])
    if not res.items and asm.get("ambiguous"):
        res.note = asm["ambiguous"]
    return res


def _list_recent(kind: str, entity: str | None = None, channel: str | None = None, n: int = 8,
                days: int | None = None, asm: dict | None = None) -> ToolResult:
    """시스템 산출물·수집물의 최신 목록 — 문서 검색이 아니라 테이블 조회. kind=docs는 최근 N일 유입 문서(제목+요약)."""
    args = {"kind": kind, "entity": entity, "channel": channel, "n": n, "days": days}
    n = max(1, min(int(n or 8), 20))
    matched_names: list[str] = []
    conn = get_connection()
    try:
        if kind in ("docs", "scrap"):
            d = max(1, min(int(days or (30 if (channel or kind == "scrap") else 1)), 90))
            where, params = ["rd.published_at >= datetime('now', ?)", "length(rd.markdown) >= 80"], [f"-{d} days"]
            if kind == "scrap":
                # 스크랩 전용 목록 — '최근 스크랩된 글'은 검색이 아니라 조회 질문이다 (D-143)
                where.append("rd.source_type = 'scrap'")
            elif not channel:
                # 미검증 소스는 일반 유입 목록에서 제외 — D-142 격리의 다섯 번째 경로 (D-143).
                # 채널을 지목했으면 명시적 요청이므로 통과시킨다(스크랩 채널을 이름으로 부른 경우).
                where.append(unverified_sql())
            # 링크만 든 스크랩 원본 메시지는 컨테이너 — 원문이 이미 별도 문서라 목록에 노이즈다 (D-143)
            where.append("NOT (rd.source_type='telegram' AND length(rd.markdown) < 400 "
                         "AND rd.id IN (SELECT src_doc_id FROM scrap_links WHERE src_doc_id IS NOT NULL))")
            if channel:
                conds, cparams, cnames = _match_sources(conn, channel)
                if not conds:
                    return ToolResult("list_recent", args, [], f"'{channel}' 채널·블로거를 구독 소스에서 찾지 못함 (피드 사이드바에서 등록해야 수집됨)")
                where.append("(" + " OR ".join(conds) + ")")
                params += cparams
                matched_names = cnames
            if entity:
                ent = resolve_entity_ex(conn, entity, asm=asm)
                if ent:
                    where.append("(rd.id IN (SELECT doc_id FROM entity_links WHERE entity_id=?) OR rd.title LIKE '%'||?||'%' OR rd.markdown LIKE '%'||?||'%')")
                    params += [ent["id"], ent["name"], ent["name"]]
            rows = conn.execute(f"""
                SELECT rd.id, rd.source_type, rd.source_id, rd.url, rd.title, rd.published_at, e.summary,
                       substr(rd.markdown,1,{ITEM_CHARS}) ex, substr(rd.markdown,1,20000) body
                FROM raw_documents rd LEFT JOIN enrichments e ON e.doc_id=rd.id
                WHERE {' AND '.join(where)} ORDER BY rd.published_at DESC LIMIT ?""", (*params, n)).fetchall()
            ent_name = ent["name"] if (entity and ent) else None
            # 출처를 항목마다 실어 보낸다 — 필터만 걸고 출처를 안 주면 종합이 "누구 글인지 모르겠다"고 거부한다 (D-143)
            from pipeline.sources import source_names
            srcs = source_names(conn, rows)
            items = []
            for r in rows:
                text = (r["summary"] or r["ex"] or "")[:ITEM_CHARS]
                if ent_name:
                    # 시황·리서치처럼 여러 종목을 다루는 문서는 요약에 이 종목이 없을 수 있다 — 언급 문장을 직접 붙인다
                    ments = _mention_sentences(r["body"] or "", ent_name, k=2)
                    if ments:
                        text += "\n언급: " + " / ".join(ments)
                who = (srcs.get(r["id"]) or {}).get("name")
                items.append({"kind": "doc", "title": (f"[{who}] " if who else "") + (r["title"] or ""),
                              "text": text[:ITEM_CHARS + 360],
                              "date": (r["published_at"] or "")[:10], "doc_id": r["id"], "href": f"/doc/{r['id']}",
                              "source_type": r["source_type"]})
            note = None
            if not items:
                note = f"최근 {d}일 " + ("스크랩된 글 없음" if kind == "scrap" else "유입 문서 없음")
            elif matched_names:
                note = f"'{channel}' → {', '.join(dict.fromkeys(matched_names))}의 문서 {len(items)}건"
            return ToolResult("list_recent", args, items, note)

        if kind == "disclosures":
            d = max(1, min(int(days or 30), 365))
            since = (date.today() - timedelta(days=d)).strftime("%Y%m%d")
            where, params = ["d.rcept_dt >= ?"], [since]
            code = None
            if entity:
                code, name = _company_code(conn, entity, asm)
                if code:
                    where.append("(c.stock_code=? OR d.corp_name=?)")
                    params += [code, name]
                elif name:
                    where.append("d.corp_name LIKE '%'||?||'%'")
                    params.append(name)
            rows = conn.execute(f"""
                SELECT d.corp_name, trim(d.report_nm) report_nm, d.rcept_dt, d.dart_url, c.stock_code
                FROM disclosures d LEFT JOIN companies c ON c.corp_code=d.corp_code
                WHERE {' AND '.join(where)} ORDER BY d.rcept_dt DESC, d.rowid DESC LIMIT ?""", (*params, n)).fetchall()
            items = [{"kind": "disclosure", "title": f"{r['corp_name']} · {r['report_nm']} · {r['rcept_dt']}",
                      "text": f"{r['report_nm']} (DART {r['dart_url'] or ''})", "date": r["rcept_dt"], "doc_id": None,
                      "href": f"/analyze/{r['stock_code']}/disclosures" if r["stock_code"] else None} for r in rows]
            return ToolResult("list_recent", args, items, None if items else f"최근 {d}일 공시 없음")

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
            code, name = _company_code(conn, entity, asm)
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
                ent = resolve_entity_ex(conn, entity, asm=asm)
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
                code, name = _company_code(conn, entity, asm)
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
    asm: dict = {}
    try:
        code, name = _company_code(conn, stock, asm)
        if not code:
            return ToolResult("get_price_history", {"stock": stock, "days": days}, [], asm.get("ambiguous") or f"'{stock}' 종목을 찾지 못함")
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
        "date": rows[-1]["trade_date"], "doc_id": None, "href": f"/analyze/{code}/summary"}], assumed=asm.get("assumed", []))


_US_NAME_ALIAS = {"아마존": "AMZN", "구글": "GOOGL", "알파벳": "GOOGL", "메타": "META", "마이크로소프트": "MSFT", "엔비디아": "NVDA",
                  "테슬라": "TSLA", "애플": "AAPL", "오라클": "ORCL", "델": "DELL", "네비우스": "NBIS", "코어위브": "CRWV",
                  "아이렌": "IREN", "브로드컴": "AVGO", "마이크론": "MU", "마벨": "MRVL", "슈마컴": "SMCI", "팔란티어": "PLTR",
                  "스노우플레이크": "SNOW", "코히런트": "COHR", "루멘텀": "LITE", "버티브": "VRT", "이튼": "ETN", "TSMC": "TSM", "ASML": "ASML",
                  # 영문 통칭 (follow의 company_name과 다른 표기)
                  "google": "GOOGL", "alphabet": "GOOGL", "facebook": "META", "aws": "AMZN", "nvidia": "NVDA", "iren": "IREN",
                  "nebius": "NBIS", "coreweave": "CRWV", "dell": "DELL", "oracle": "ORCL", "microsoft": "MSFT", "amazon": "AMZN", "meta": "META"}


def _resolve_ticker(conn, name: str) -> tuple[str | None, str]:
    """회사명(한/영)·티커 → transcript_follow 티커. 순서: 티커 직접 → 별칭표 → follow company_name 부분일치 → 엔티티 id 매칭."""
    q = (name or "").strip()
    if not q:
        return None, q
    follows = conn.execute("SELECT ticker, company_name, entity_id FROM transcript_follow").fetchall()
    by_ticker = {f["ticker"]: f for f in follows}
    if q.upper() in by_ticker:
        return q.upper(), by_ticker[q.upper()]["company_name"]
    alias = _US_NAME_ALIAS.get(q) or _US_NAME_ALIAS.get(q.lower())
    if alias and alias in by_ticker:
        return alias, by_ticker[alias]["company_name"]
    for f in follows:
        if f["company_name"] and (q.lower() in f["company_name"].lower() or f["company_name"].lower() in q.lower()):
            return f["ticker"], f["company_name"]
    ent = resolve_entity(conn, q, prefer=("company",))
    if ent:
        for f in follows:
            if f["entity_id"] == ent["id"]:
                return f["ticker"], f["company_name"]
    return None, q


def get_transcripts(companies: list[str] | str, n_per: int = 1) -> ToolResult:
    """미국 기업 실적 컨콜 핵심 정리(실적·가이던스·경영진 코멘트·Q&A) — 회사별 최신 n건."""
    names = companies if isinstance(companies, list) else [companies]
    n_per = max(1, min(int(n_per or 1), 3))
    conn = get_connection()
    items, missing, unresolved = [], [], []
    try:
        for nm in names[:10]:
            ticker, label = _resolve_ticker(conn, str(nm))
            if not ticker:
                unresolved.append(str(nm))
                continue
            rows = conn.execute("""
                SELECT id, ticker, fiscal_year, fiscal_period, call_date, digest FROM transcripts
                WHERE ticker=? AND digest IS NOT NULL ORDER BY call_date DESC LIMIT ?""", (ticker, n_per)).fetchall()
            if not rows:
                missing.append(f"{label}({ticker})")
                continue
            for r in rows:
                items.append({"kind": "transcript",
                              "title": f"{label}({r['ticker']}) FY{r['fiscal_year']} {r['fiscal_period']} 실적 컨콜 · {r['call_date']}",
                              "text": (r["digest"] or "")[:2200], "date": r["call_date"], "doc_id": None,
                              "href": f"/follow/transcripts?t={r['id']}"})
    finally:
        conn.close()
    notes = []
    if missing:
        notes.append("컨콜 미수집: " + ", ".join(missing) + " (팔로우 중이나 아직 수집·정리 안 됨)")
    if unresolved:
        notes.append("팔로우 목록에 없는 회사: " + ", ".join(unresolved))
    return ToolResult("get_transcripts", {"companies": names, "n_per": n_per}, items,
                      (" · ".join(notes) if notes else None) if items else (" · ".join(notes) or "컨콜 정리 없음"))


def get_trade(item: str | None = None, months: int = 12) -> ToolResult:
    """관세청 수출입 통계(D-140) — 품목 지정: 월별 수출·YoY·판정(z)·수혜종목 / 미지정: 최신월 급등·급감 하이라이트."""
    from pipeline.trade_metrics import derive, highlights, LOOKBACK, classify_all, DEFAULTS
    months = max(3, min(int(months or 12), 36))
    conn = get_connection()
    try:
        follows = [dict(r) for r in conn.execute("SELECT hs_code, item_name, group_label FROM trade_follow WHERE active=1")]
        if not item:
            h = highlights(limit=6)
            if not h.get("period"):
                return ToolResult("get_trade", {"item": None}, [], "수출입 통계 없음")
            lines = [f"기준월 {h['period']} · 팔로우 {len(follows)}품목 · 수출 합계 ${h['total_usd'] / 1e9:,.1f}B (급등 판정: 품목별 과거 YoY 분포 대비 로버스트 z ≥ 2, 규모 ≥ $10M)"]
            for label, rows in (("급등·신규", h["surge"]), ("급감", h["plunge"])):
                if rows:
                    lines.append(f"[{label}]")
                    lines += [f"- {r['item_name']} (HS {r['hs_code']}, {r['group_label']}): 수출 ${(r['value'] or 0) / 1e6:,.0f}M, {r.get('reason')}"
                              + (f", 전체 증감 기여 {r['contribution'] * 100:.0f}%" if r.get("contribution") is not None else "") for r in rows]
            gl = [f"{g['group_label']} ${g['value'] / 1e9:,.1f}B(급등 {g['surge']}·급감 {g['plunge']})" for g in h["groups"][:8]]
            lines.append("[분류별] " + " · ".join(gl))
            return ToolResult("get_trade", {"item": None}, [{
                "kind": "trade", "title": f"수출입 하이라이트 {h['period']} — 급등 {len(h['surge'])}·급감 {len(h['plunge'])}",
                "text": "\n".join(lines)[:BODY_CHARS + 800], "date": h["period"], "doc_id": None, "href": "/follow/trade"}])
        key = item.replace(" ", "").lower()
        sel = [f for f in follows if key in (f["item_name"] + (f["group_label"] or "") + f["hs_code"]).replace(" ", "").lower()]
        if not sel:
            return ToolResult("get_trade", {"item": item}, [], f"'{item}' 품목이 수출입 팔로우 목록에 없음 (분류: "
                              + ", ".join(sorted({f['group_label'] or '미분류' for f in follows})) + ")")
        items = []
        for f in sel[:6]:
            raw = [dict(r) for r in conn.execute("SELECT period, export_usd, import_usd FROM trade_stats WHERE hs_code=? ORDER BY period", (f["hs_code"],))]
            if not raw:
                continue
            der = derive(raw, "export")
            lines = []
            for d in der[-months:]:
                yoy = f" YoY {d['yoy'] * 100:+.0f}%" if d.get("yoy") is not None else ""
                z = f" z{d['z']:+.1f}" if d.get("z") is not None else ""
                lines.append(f"{d['period']} 수출 ${(d['value'] or 0) / 1e6:,.0f}M{yoy}{z}")
            last = der[-1]
            grid = classify_all(last, mode="zscore", z_threshold=DEFAULTS["z_threshold"], fixed_threshold=DEFAULTS["fixed_threshold"], min_usd=DEFAULTS["min_usd"])
            verdict = "판정(" + last["period"] + "): " + " · ".join(f"{m} {g['flag']}({g['reason']})" for m, g in grid.items())
            bene = conn.execute("SELECT name, rel, reason FROM trade_beneficiaries WHERE hs_code=? LIMIT 6", (f["hs_code"],)).fetchall()
            btxt = ("\n관련 종목(파급 논리, 가설): " + " / ".join(f"{b['name']}({b['rel']}) — {(b['reason'] or '')[:80]}" for b in bene)) if bene else ""
            items.append({"kind": "trade", "title": f"{f['item_name']} (HS {f['hs_code']}, {f['group_label']}) 월별 수출 최근 {min(months, len(der))}개월",
                          "text": "\n".join(lines) + "\n" + verdict + btxt, "date": der[-1]["period"], "doc_id": None,
                          "href": f"/follow/trade?hs={f['hs_code']}"})
    finally:
        conn.close()
    return ToolResult("get_trade", {"item": item, "months": months}, items, None if items else "수출입 통계 없음")


def get_saved(kind: str | None = None, query: str | None = None, n: int = 15) -> ToolResult:
    """사용자가 '저장됨'에 북마크한 산출물·문서(제목·부제·메모)."""
    n = max(1, min(int(n or 15), 30))
    conn = get_connection()
    try:
        where, params = [], []
        if kind:
            where.append("kind=?"); params.append(kind)
        if query:
            toks = [t for t in re.split(r"[^0-9A-Za-z가-힣]+", query) if len(t) >= 2][:4]
            if toks:
                where.append("(" + " OR ".join("(title LIKE '%'||?||'%' OR subtitle LIKE '%'||?||'%' OR note LIKE '%'||?||'%')" for _ in toks) + ")")
                params += [x for t in toks for x in (t, t, t)]
        rows = conn.execute(f"SELECT kind, ref, url, title, subtitle, note, created_at FROM saved_items"
                            f"{(' WHERE ' + ' AND '.join(where)) if where else ''} ORDER BY created_at DESC LIMIT ?", (*params, n)).fetchall()
        items = []
        for r in rows:
            doc_id = int(r["ref"]) if r["kind"] == "doc" and str(r["ref"]).isdigit() else None
            summary = None
            if doc_id:
                e = conn.execute("SELECT summary FROM enrichments WHERE doc_id=?", (doc_id,)).fetchone()
                summary = e["summary"] if e else None
            text = " / ".join(x for x in [r["subtitle"], summary, (f"내 메모: {r['note']}" if r["note"] else None)] if x)
            items.append({"kind": "saved", "title": f"[{r['kind']}] {r['title'] or ''}", "text": text[:ITEM_CHARS + 200],
                          "date": (r["created_at"] or "")[:10], "doc_id": doc_id, "href": r["url"]})
    finally:
        conn.close()
    return ToolResult("get_saved", {"kind": kind, "query": query}, items, None if items else "저장된 항목 없음")


def get_proxies(query: str, n: int = 8) -> ToolResult:
    """핵심질문의 관측 프록시(레지스트리) + 관측치 시계열 — 질문에 대한 '실데이터 판정' 재료."""
    n = max(1, min(int(n or 8), 15))
    toks = [t for t in re.split(r"[^0-9A-Za-z가-힣]+", query or "") if len(t) >= 2][:5]
    conn = get_connection()
    try:
        where, params = ["p.active=1"], []
        if toks:
            where.append("(" + " OR ".join("(p.label LIKE '%'||?||'%' OR p.tickers LIKE '%'||?||'%' OR p.key LIKE '%'||?||'%')" for _ in toks) + ")")
            params += [x for t in toks for x in (t, t, t)]
        rows = conn.execute(f"""
            SELECT p.id, p.label, p.tickers, p.unit, p.modality, p.yes_direction, p.sub_question_id,
                   (SELECT COUNT(*) FROM proxy_observations o WHERE o.proxy_id=p.id) n_obs
            FROM proxy_registry p WHERE {' AND '.join(where)} ORDER BY n_obs DESC, p.id DESC LIMIT ?""", (*params, n)).fetchall()
        items = []
        for p in rows:
            obs = conn.execute("SELECT observed_at, value_num, value_text, direction, source_type FROM proxy_observations "
                               "WHERE proxy_id=? ORDER BY observed_at DESC LIMIT 4", (p["id"],)).fetchall()
            qtext, qid = None, None
            if p["sub_question_id"]:
                sq = conn.execute("SELECT sq.text, sq.question_id, q.text qtext FROM sub_questions sq LEFT JOIN questions q ON q.id=sq.question_id WHERE sq.id=?",
                                  (p["sub_question_id"],)).fetchone()
                if sq:
                    qtext, qid = (sq["qtext"] or sq["text"]), sq["question_id"]
            head = f"측정: {p['label']} · 종류 {p['modality'] or '-'} · '예' 방향 {p['yes_direction'] or '-'}" + (f" · 단위 {p['unit']}" if p["unit"] else "") + (f" · 티커 {p['tickers']}" if p["tickers"] else "")
            if qtext:
                head += f"\n질문: {qtext[:120]}"
            def _fmt(v):
                return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:g}"
            ol = [f"- {o['observed_at']}: " + (_fmt(o["value_num"]) if o["value_num"] is not None else "") + (f" {o['value_text'][:90]}" if o["value_text"] else "") + f" ({o['direction'] or '-'}, {o['source_type'] or '-'})" for o in obs]
            items.append({"kind": "proxy", "title": f"프록시 · {p['label'][:60]} (관측 {p['n_obs']}건)",
                          "text": head + ("\n관측:\n" + "\n".join(ol) if ol else "\n관측 없음"), "date": obs[0]["observed_at"] if obs else None,
                          "doc_id": None, "href": f"/question/{qid}" if qid else "/questions"})
    finally:
        conn.close()
    return ToolResult("get_proxies", {"query": query}, items, None if items else "해당 프록시 없음")


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
    asm: dict = {}
    try:
        ent = resolve_entity_ex(conn, entity, asm=asm)
        if not ent:
            return ToolResult("get_worldmodel", {"entity": entity}, [], asm.get("ambiguous") or f"'{entity}' 엔티티 없음")
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
    asm: dict = {}
    code, name = _company_code(conn, stock, asm)
    conn.close()
    if not code:
        return ToolResult("get_lens", {"stock": stock}, [], asm.get("ambiguous") or f"'{stock}' 종목을 찾지 못함")
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
                      None if items else f"{name} 렌즈 판독 미생성", assumed=asm.get("assumed", []))


def get_quote(stocks: list[str] | str) -> ToolResult:
    """질문 속 종목의 실시간 시세. 종목명은 resolve_entity로 해석(회사 우선) — 텍스트 부분일치는 '하이닉스'→'이닉스' 오탐."""
    from pipeline.quotes import fetch_quotes
    names = stocks if isinstance(stocks, list) else [stocks]
    conn = get_connection()
    asm: dict = {}
    try:
        resolved = []
        for nm in names:
            code, name = _company_code(conn, str(nm), asm)
            if code:
                resolved.append((code, name))
    finally:
        conn.close()
    if not resolved:
        return ToolResult("get_quote", {"stocks": names}, [], asm.get("ambiguous") or "종목명을 해석하지 못함")
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
        "date": date.today().isoformat(), "doc_id": None, "href": None}], assumed=asm.get("assumed", []))


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
    "search_docs": {"fn": search_docs, "args": {"query", "since_days", "source", "entity", "variants", "channel"},
                    "desc": "수집 문서(텔레그램·블로그·유튜브·컨콜·뉴스) 의미+키워드 검색. 사건·의견·언급을 찾을 때. "
                            "args: query(독립형 검색어, 필수), variants(검색어 변형 2~3개 — 영문명·티커·약어·다른 표현. 예: [\"SK hynix HBM margin\", \"하이닉스 HBM 수익성\"]), "
                            "since_days(7|30|90), source(telegram|blog|youtube|transcript|canon|**scrap**), entity(엔티티명 — 별칭·키워드로 자동 확장). "
                            "**scrap=개인 투자자 블로그 스크랩(미검증 주장)** — 기본 검색에서 빠져 있고 이 인자로 명시할 때만 조회된다. "
                            "'다른 투자자들은 뭐라 하나·요즘 뭘 스터디하나'에만 쓴다. "
                            "**channel(채널·블로거·유튜버 이름) = 그 소스 안에서만 검색** — '그 사람이 뭐라 했나·어느 종목을 강조했나'류에 필수"},
    "open_doc": {"fn": open_doc, "args": {"doc_id"},
                 "desc": "특정 문서 전문. 사용자가 이전 답변의 인용 문서를 더 보자고 할 때. args: doc_id(정수)"},
    "list_recent": {"fn": list_recent, "args": {"kind", "entity", "channel", "n", "days"},
                    "desc": "최신 목록 조회(문서 검색 아님). kind=scrap(최근 스크랩된 개인 블로그 글 목록 — '요즘 뭘 스터디하나·스크랩된 거 보여줘'에 필수, 미검증) · kind=docs(최근 days일 유입 문서 제목+요약 — '오늘/이번주 무슨 일·이슈'에 필수; entity로 종목 좁힘; "
                            "**channel=블로거·채널·작성자 이름**('메르','슈카','삼성증권')이면 그 소스의 글만 — '누가 최근에 뭘 썼나' 질문에 필수)|"
                            "disclosures(DART 공시 최신, entity=종목)|narratives(생성된 내러티브)|digests(종목 1D/1W 요약, entity 필수)|youtube(구독 채널 영상, channel)|"
                            "signals(언급급증·신고가 등 신호)|actions(유무증·합병 등 기업활동 요약). args: kind, entity, channel, n(≤20), days(1~90)"},
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
    "get_trade": {"fn": get_trade, "args": {"item", "months"},
                  "desc": "관세청 수출입 통계(팔로우 ~180품목: 반도체·전자부품·2차전지·디스플레이·기계·바이오·화장품·식품 등 15분류). item 지정=월별 수출·YoY·급등판정(z)·수혜종목, "
                          "미지정=최신월 급등·급감 하이라이트+분류별 합계. '수출·무역·수출입 추이·어떤 품목이 튀었나' 질문에. args: item(품목명·분류·HS 일부, 선택), months(3~36)"},
    "get_saved": {"fn": get_saved, "args": {"kind", "query", "n"},
                  "desc": "사용자가 '저장됨'에 북마크한 글·내러티브·종합(제목·부제·요약·내 메모). '내가 저장한/북마크한/모아둔' 질문에. args: kind(doc|narrative|synthesis, 선택), query(키워드, 선택), n"},
    "get_proxies": {"fn": get_proxies, "args": {"query", "n"},
                    "desc": "핵심질문의 관측 프록시(무엇을 측정·'예' 방향·단위·티커)와 관측치 시계열(컨콜 등에서 추출). '프록시·관측 지표·추적 중인 수치·실데이터로 확인됐나' 질문에. args: query(주제·질문 키워드), n"},
    "get_transcripts": {"fn": get_transcripts, "args": {"companies", "n_per"},
                        "desc": "미국 기업 실적 컨콜 핵심 정리(실적 하이라이트·가이던스·경영진 코멘트·Q&A). '실적발표·컨콜·가이던스·경영진이 뭐라 했나' 질문에 반드시. "
                                "args: companies(회사명 한/영 또는 티커 배열, 예: [\"아마존\", \"Oracle\", \"NBIS\"]), n_per(회사별 최신 건수 1~3)"},
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
