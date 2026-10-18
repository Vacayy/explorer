"""밸류체인 트리 보고서 (docs/specs/value-chain.md §16) — 루트에서 공급 쪽으로 타고 들어가며 칸마다 사실·기대·문서를 모아 자연어 보고서.

버튼으로 요청할 때만 만든다(사용자 결정, 비싼 생성은 승인 뒤로). 단계:
1. 트리 고르기(LLM 0): 루트에서 공급 방향 연결을 따라 깊이 3·칸 12까지, 추정 증가액(§14)이 큰 가지 우선
2. 칸별 자료 묶음(LLM 0): 사실(read_map)·기대(vc_expectations)·컨퍼런스콜 요약(transcripts.digest)·피드(한국 종목 연결 + 칸 이름)
3. 칸 메모(sonnet): 입력 해시가 같으면 chain_node_notes에서 재사용 — 재료가 바뀐 칸만 다시 쓴다
4. 종합(opus + 웹 검색 상시, 사용자 결정): 칸 메모 → 보고서. 출처 없는 문장 금지, 사실과 기대 구분
LLM 호출 동안 DB 쓰기 트랜잭션을 잡지 않는다(쓰기 순간에만 연결) — LLM 작업이 쓰기 잠금을 오래 쥐어 다른 수집이 실패하던 문제.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import re

from database import get_connection

DEPTH, MAX_NODES = 3, 12
NOTE_MODEL, SYNTH_MODEL = "sonnet", "opus"
DOCS_PER_NODE, DOC_CHARS, DOC_DAYS = 6, 700, 30
WEB_SEARCH_CAP = 5

NOTE_SYSTEM = """너는 반도체·IT 하드웨어 밸류체인 애널리스트다. 한 칸(공급 단계)의 자료 묶음만 보고 짧은 메모를 쓴다.
규칙:
- 사실(관측 데이터·공시·컨콜)과 기대(애널리스트 컨센서스·리서치 전망·증권사 견해)를 반드시 구분해 쓴다.
- 모든 주장 끝에 출처를 단다: 문서는 [D문서번호], 컨콜은 [C티커 날짜], 리서치 전망은 [W: 그 전망의 url], 데이터는 [데이터]. 자료에 없는 내용은 쓰지 않는다.
- 피드 문서는 키워드로 모은 것이라 이 칸과 무관한 문서가 섞여 있다 — 무관한 문서는 무시하고 인용하지 않는다.
- 형식(마크다운, 10~16줄):
  **지금 일어나는 일** — 2~4개 불릿
  **기대와의 괴리** — 관측 vs 기대, 개정 방향
  **반증 조건** — 이 흐름이 틀렸다고 판단할 관측 1~2개
  **자료 공백** — 판단에 필요한데 없는 것(종합 단계에서 웹으로 보충할 대상)"""

SYNTH_SYSTEM = f"""너는 반도체·IT 하드웨어 밸류체인 수석 애널리스트다. 루트에서 공급 쪽으로 내려가는 트리의 칸 메모들을 종합해 한국어 보고서를 쓴다.
규칙:
- 사실과 기대를 문단 안에서도 구분한다(예: '관측: … / 기대: …').
- 모든 주장에 출처를 단다: 칸 메모의 [D…]·[C…]·[데이터]를 그대로 옮기고, 웹에서 찾은 내용은 [W: URL]로. 출처 없는 문장은 쓰지 않는다.
- 웹 검색은 칸 메모의 '자료 공백' 중 판단에 중요한 것만, 최대 {WEB_SEARCH_CAP}회. 검색 결과도 사실과 전망을 구분한다.
- 예측이 아니라 조준이다: 결론은 '어디를 더 봐야 하나'와 반증 조건으로 끝낸다. 매수·매도 권유를 하지 않는다.
- 목차(마크다운 ##):
  ## 결론 먼저 — 돈이 지금 어디로 가장 세게 흐르고, 기대는 어디서 앞서거나 뒤처지는가 (3~5불릿)
  ## 흐름 경로 — 루트에서 칸으로 이어지는 돈의 길(추정 증가액이 큰 순)
  ## 칸별 사실·기대·괴리 — 칸마다 ### 소제목
  ## 반증 조건 — 전체 그림이 틀렸다고 볼 관측
  ## 확인할 것 — 다음 데이터 발표·이벤트"""


def select_tree(root: str, vmap: dict, flows: list[dict], depth: int = DEPTH, max_nodes: int = MAX_NODES) -> list[dict]:
    """루트에서 공급 방향으로(이 칸에 파는 칸들) — 추정 증가액이 큰 연결부터 꺼내는 최대 힙. 같은 칸은 한 번만"""
    from pipeline.value_chain import EDGES
    name = {n["key"]: n["name"] for n in vmap["nodes"]} | {d["key"]: d["name"] for d in vmap["demands"]}
    flow = {(f["from"], f["to"]): f.get("flow_usd") for f in flows}
    tree = [{"key": root, "name": name.get(root, root), "parent": None, "depth": 0, "flow_usd": None}]
    seen, heap = {root}, []

    def push(node: str, d: int):
        for a, b, *_ in EDGES:                        # a가 b에 판다 → b(사는 칸)에서 a(파는 칸)로 내려간다
            if b == node and a not in seen:
                heapq.heappush(heap, (-(flow.get((a, b)) or 0.0), d + 1, a, b))
    push(root, 0)
    while heap and len(tree) < max_nodes:
        neg, d, a, b = heapq.heappop(heap)
        if a in seen or d > depth:
            continue
        seen.add(a)
        tree.append({"key": a, "name": name.get(a, a), "parent": b, "depth": d, "flow_usd": -neg or None})
        push(a, d)
    return _dfs(tree)


def _dfs(tree: list[dict]) -> list[dict]:
    """부모 바로 아래에 자식이 오는 순서(추정 증가액 큰 자식 먼저) — 꺼낸 순서대로 들여쓰기만 하면
    부모를 잘못 읽는다(첫 보고서가 '구리 → ASML'을 공급 관계로 오독, 실제 부모는 파운드리)"""
    kids: dict[str | None, list[dict]] = {}
    for t in tree:
        kids.setdefault(t["parent"], []).append(t)
    out: list[dict] = []

    def walk(p: str | None):
        for t in sorted(kids.get(p, []), key=lambda x: -(x["flow_usd"] or 0)):
            out.append(t)
            walk(t["key"])
    walk(None)
    return out


GENERIC = {"AI", "IC", "ODM", "칩", "서버", "수요", "투자", "부품", "장비", "소재", "생산", "한국", "대만", "미국", "일본", "중국", "데이터센터"}


def _docs(conn, node: dict, kr: list[str], names: list[str]) -> list[dict]:
    """칸 피드 문서 — 한국 종목 문서 연결 + 구성 회사 이름·칸 고유 낱말(제목), 최근 30일 최신순, 같은 제목은 하나만.
    칸 이름 낱말만으로 찾으면 'AI'·'서버' 같은 흔한 말에 무관한 문서가 섞인다(2026-10-18 미리보기)"""
    rows: dict[int, dict] = {}
    if kr:
        for r in conn.execute(f"""SELECT DISTINCT d.id, d.title, d.url, d.published_at, d.source_type, substr(d.markdown,1,{DOC_CHARS}) body
            FROM entity_links el JOIN entities e ON e.id=el.entity_id JOIN raw_documents d ON d.id=el.doc_id
            WHERE el.link_type='stock' AND e.aliases IN ({','.join('?' * len(kr))}) AND d.published_at >= datetime('now','-{DOC_DAYS} days')
            ORDER BY d.published_at DESC LIMIT {DOCS_PER_NODE}""", kr):
            rows[r["id"]] = dict(r)
    words = names + [w for w in re.split(r"[()·,\s/]+", node["name"]) if len(w) >= 2 and w not in GENERIC]
    for w in words[:6]:
        if len(rows) >= DOCS_PER_NODE:
            break
        for r in conn.execute(f"""SELECT id, title, url, published_at, source_type, substr(markdown,1,{DOC_CHARS}) body FROM raw_documents
            WHERE title LIKE ? AND published_at >= datetime('now','-{DOC_DAYS} days') ORDER BY published_at DESC LIMIT 3""", (f"%{w}%",)):
            rows.setdefault(r["id"], dict(r))
    uniq: dict[str, dict] = {}
    for r in sorted(rows.values(), key=lambda r: r["published_at"] or "", reverse=True):
        uniq.setdefault((r["title"] or "").strip(), r)
    return list(uniq.values())[:DOCS_PER_NODE]


def _calls(conn, tickers: list[str]) -> list[dict]:
    """칸 미국 회사의 최근 컨콜 요약(기존 digest 재사용)"""
    out = []
    for t in tickers:
        r = conn.execute("SELECT ticker, call_date, fiscal_year, fiscal_period, digest FROM transcripts WHERE ticker=? AND digest IS NOT NULL "
                         "ORDER BY call_date DESC LIMIT 1", (t,)).fetchone()
        if r:
            out.append({"ticker": r["ticker"], "date": r["call_date"], "period": f"{r['fiscal_year']} {r['fiscal_period']}", "digest": (r["digest"] or "")[:1800]})
    return out


def dossier(conn, key: str, vmap: dict, exp: dict, flow: dict) -> dict:
    """칸 자료 묶음(결정적) — 사실·기대·컨콜·피드"""
    from pipeline.us_fundamentals import EXTERNAL, TARGETS
    from pipeline.value_chain import US_OBS
    node = next((n for n in vmap["nodes"] if n["key"] == key), None) or next(d for d in vmap["demands"] if d["key"] == key)
    fr = next((r for r in flow["nodes"] if r["key"] == key), {}) or next((d for d in flow.get("demands", []) if d["key"] == key), {})
    facts = {k: node.get(k) for k in ("name", "description", "obs_label", "period", "yoy_3m", "yoy_3m_prev", "state", "state_z", "obs_kind", "obs_caveat")}
    facts |= {"규모_usd": fr.get("level_usd"), "증가액_usd": fr.get("increment_usd"),
              "교차확인": [{k: a.get(k) for k in ("label", "yoy_3m", "state", "period")} for a in node.get("aux", []) if not a.get("missing")],
              "P×Q": [{k: p.get(k) for k in ("item", "value_yoy", "price_yoy", "qty_yoy", "verdict")} for p in node.get("pxq", [])],
              "구성회사_분기": [{k: m.get(k) for k in ("name", "metric", "q", "value", "yoy")} for m in node.get("us_members", [])]}
    e = exp["nodes"].get(key) or {}
    expect = {k: e.get(k) for k in ("exp_0q", "exp_0y", "exp_1y", "eps_rev_30d", "eps_rev_90d", "gap_pp", "note")} | {
        "리서치전망": [{k: c.get(k) for k in ("source_org", "published_at", "subject", "metric", "target_period", "value_low", "value_high", "quote", "url")}
                   for c in e.get("claims", [])[:6]]}
    from pipeline.us_fundamentals import NAMES
    tickers = [t for t, m, u in TARGETS + EXTERNAL if key in US_OBS and u == US_OBS[key][0] and m == "revenue"]
    tickers += [m["symbol"] for m in e.get("members", []) if "." not in m["symbol"] and m["symbol"] not in tickers]   # 기대 구성 미국 회사(메모리 → 마이크론)
    kr = [k["code"] for k in node.get("kr", [])]
    names = [t["name"] for t in node.get("tw", [])] + [NAMES[t] for t in tickers if t in NAMES]
    return {"key": key, "사실": facts, "기대": expect, "컨콜": _calls(conn, tickers), "피드": _docs(conn, node, kr, names)}


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _note(key: str, d: dict) -> str:
    """칸 메모 — 같은 자료 묶음이면 캐시"""
    from pipeline.llm import run
    h = _hash(d)
    conn = get_connection()
    try:
        hit = conn.execute("SELECT body FROM chain_node_notes WHERE node_key=? AND inputs_hash=?", (key, h)).fetchone()
    finally:
        conn.close()
    if hit:
        return hit["body"]
    docs = "\n".join(f"[D{x['id']}] {x['published_at'][:10] if x['published_at'] else ''} {x['source_type']} — {x['title']}\n{(x['body'] or '').strip()}" for x in d["피드"])
    calls = "\n".join(f"[C{c['ticker']} {c['date']}] {c['period']}\n{c['digest']}" for c in d["컨콜"])
    prompt = (f"칸: {d['사실']['name']} ({key})\n\n## 사실(관측 데이터)\n{json.dumps(d['사실'], ensure_ascii=False, default=str)}\n\n"
              f"## 기대(컨센서스·리서치 전망)\n{json.dumps(d['기대'], ensure_ascii=False, default=str)}\n\n## 컨퍼런스콜 요약\n{calls or '(없음)'}\n\n"
              f"## 피드 문서(최근 {DOC_DAYS}일)\n{docs or '(없음)'}\n\n위 자료로 칸 메모를 써라.")
    body = run(prompt, system=NOTE_SYSTEM, model=NOTE_MODEL, timeout=300, job="chain_report_note").text.strip()
    conn = get_connection()
    try:
        conn.execute("INSERT OR REPLACE INTO chain_node_notes (node_key, inputs_hash, body, model) VALUES (?,?,?,?)", (key, h, body, NOTE_MODEL))
        conn.commit()
    finally:
        conn.close()
    return body


def _update(rid: int, **cols) -> None:
    conn = get_connection()
    try:
        conn.execute(f"UPDATE chain_reports SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?", (*cols.values(), rid))
        conn.commit()
    finally:
        conn.close()


def start(root: str) -> tuple[int, bool]:
    """보고서 행을 만들고 (id, 새로 만들었나)를 돌려준다(생성은 build가 백그라운드에서). 같은 루트가 30분 안에 돌고 있으면 그 id"""
    conn = get_connection()
    try:
        r = conn.execute("SELECT id FROM chain_reports WHERE root=? AND status='running' AND created_at >= datetime('now','-30 minutes') "
                         "ORDER BY id DESC LIMIT 1", (root,)).fetchone()
        if r:
            return r["id"], False
        cur = conn.execute("INSERT INTO chain_reports (root, status, progress, model) VALUES (?, 'running', '트리 고르는 중', ?)",
                           (root, f"{NOTE_MODEL}+{SYNTH_MODEL}"))
        conn.commit()
        return cur.lastrowid, True
    finally:
        conn.close()


def build(rid: int, root: str) -> None:
    """트리 → 칸 자료 묶음 → 칸 메모(n/m) → 종합(웹 검색) → 저장. 실패는 status와 job_runs에 남긴다(조용한 실패 금지)"""
    from pipeline.llm import run
    from pipeline.ops import record_run
    from pipeline.value_chain import read_map
    from pipeline.value_chain_flow import compute
    from pipeline.vc_expectations import with_observed
    try:
        vmap = read_map()
        flow = compute(vmap)
        exp = with_observed(vmap)
        tree = select_tree(root, vmap, flow.get("edge_flows", []))
        _update(rid, tree_json=json.dumps(tree, ensure_ascii=False), progress=f"칸 자료 모으는 중 (0/{len(tree)})")
        conn = get_connection()
        try:
            dossiers = [dossier(conn, t["key"], vmap, exp, flow) for t in tree]
        finally:
            conn.close()
        notes, missing = {}, []
        for i, d in enumerate(dossiers, 1):
            _update(rid, progress=f"칸 메모 쓰는 중 ({i}/{len(dossiers)}) — {d['사실']['name']}")
            try:
                notes[d["key"]] = _note(d["key"], d)
            except Exception as e:  # noqa: BLE001 — 한 칸 실패는 빼고 종합(partial)
                missing.append({"key": d["key"], "name": d["사실"]["name"], "error": f"{type(e).__name__}: {str(e)[:120]}"})
        if not notes:
            raise RuntimeError("칸 메모를 하나도 쓰지 못함: " + "; ".join(m["error"] for m in missing[:3]))
        refs = _refs(dossiers)
        _update(rid, progress="종합 보고서 쓰는 중(웹 검색 포함)")
        names = {t["key"]: t["name"] for t in tree}
        path = "\n".join(f"{'  ' * t['depth']}- {t['name']}" + (f" (→ {names[t['parent']]}에 판다, 이 연결 추정 증가액 {t['flow_usd'] / 1e9:+.1f}B USD)"
                                                              if t["parent"] else "") for t in tree)
        body_notes = "\n\n".join(f"### {t['name']} ({t['key']})\n{notes[t['key']]}" for t in tree if t["key"] in notes)
        prompt = (f"루트: {tree[0]['name']}\n\n## 트리(루트 → 공급 쪽, 들여쓰기 = 깊이, 자식은 부모 바로 아래)\n{path}\n\n"
                  "'이 연결 추정 증가액'은 실제 거래액이 아니다 — 파는 칸의 전년 대비 증가액을 그 칸이 파는 칸들에 사는 칸 규모 비례로 나눈 몫이라, "
                  "칸 메모의 칸 전체 증가액보다 작을 수 있고 위아래로 더할 수 없다. 이 차이를 보고서에서 오류로 지적하지 마라.\n\n"
                  f"## 칸 메모\n{body_notes}\n\n"
                  + (f"## 메모가 빠진 칸\n{', '.join(m['name'] for m in missing)}\n\n" if missing else "")
                  + "위 칸 메모들로 보고서를 써라.")
        res = run(prompt, system=SYNTH_SYSTEM, model=SYNTH_MODEL, tools=("WebSearch", "WebFetch"), timeout=1200, job="chain_report")
        status = "partial" if missing else "done"
        _update(rid, status=status, progress=None, body=res.text.strip(), refs_json=json.dumps(refs, ensure_ascii=False),
                missing_json=json.dumps(missing, ensure_ascii=False), inputs_hash=_hash([notes, tree]), finished_at=_now())
        record_run("chain_report", "partial" if missing else "ok", f"root {root} · 칸 {len(notes)}/{len(tree)}")
    except Exception as e:  # noqa: BLE001
        _update(rid, status="error", progress=None, error=f"{type(e).__name__}: {str(e)[:400]}", finished_at=_now())
        record_run("chain_report", "error", f"root {root} · {type(e).__name__}: {str(e)[:150]}")


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _refs(dossiers: list[dict]) -> list[dict]:
    """인용 가능한 문서 목록(결정적) — 본문 [D…]·[C…]를 화면에서 원문으로 잇는다"""
    seen, out = set(), []
    for d in dossiers:
        for x in d["피드"]:
            if (k := f"D{x['id']}") not in seen:
                seen.add(k)
                out.append({"ref": k, "title": x["title"], "url": x["url"], "date": (x["published_at"] or "")[:10], "kind": x["source_type"]})
        for c in d["컨콜"]:
            if (k := f"C{c['ticker']} {c['date']}") not in seen:
                seen.add(k)
                out.append({"ref": k, "title": f"{c['ticker']} {c['period']} 컨퍼런스콜", "url": None, "date": c["date"], "kind": "transcript"})
    return out


def read(rid: int) -> dict | None:
    conn = get_connection()
    try:
        r = conn.execute("SELECT * FROM chain_reports WHERE id=?", (rid,)).fetchone()
    finally:
        conn.close()
    if not r:
        return None
    j = lambda v: json.loads(v) if v else []  # noqa: E731
    return {**{k: r[k] for k in ("id", "root", "status", "progress", "body", "model", "error", "created_at", "finished_at")},
            "tree": j(r["tree_json"]), "refs": j(r["refs_json"]), "missing": j(r["missing_json"])}


def history(root: str, limit: int = 10) -> list[dict]:
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT id, root, status, created_at, finished_at FROM chain_reports WHERE root=? "
                                              "ORDER BY id DESC LIMIT ?", (root, limit))]
    finally:
        conn.close()


def preview(root: str) -> dict:
    """생성 전 확인용 — 고른 트리와 예상 LLM 호출 수(캐시 적중 칸은 빼고)"""
    from pipeline.value_chain import read_map
    from pipeline.value_chain_flow import compute
    vmap = read_map()
    flow = compute(vmap)
    tree = select_tree(root, vmap, flow.get("edge_flows", []))
    return {"root": root, "tree": tree, "calls": {"node_notes_max": len(tree), "synthesis": 1, "web_search_cap": WEB_SEARCH_CAP},
            "models": {"note": NOTE_MODEL, "synthesis": SYNTH_MODEL}}
