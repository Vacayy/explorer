"""통합 리포트 — 공유 인과로 엮인 내러티브들을 애널리스트 참고자료로 취합하고,
같은 종목의 '내러티브별 다른 파급'을 다 모은 뒤 반영해 종목을 다시 분석 → Top-down 리포트.

연쇄 LLM(오케스트레이션 도구 아님, scenario/mega처럼 순차 호출):
  취합(LLM 0) → 종목별 다각도 재분석 ×M(sonnet) → 리포트 종합 ×1(opus). 전부 캐시.
스펙: docs/specs/integrated-report.md. 선례: mega_narrative(공유 노드 서사).
"""
import hashlib
import json

from pipeline.enrich import _call_claude_code, llm_engine
from pipeline.upside_model import _anchor
from pipeline.research_candidates import _rs_short

TOP_RELATED = 5    # 공유 이웃 내러티브 상위
TOP_STOCKS = 6     # 종목 재분석 대상 (교차 현저성 순)
AUGMENT_CAP = 2    # scenario 없는 구성 내러티브 자동 보강 상한(opus, 비용 통제) — ②
BODY_EXCERPT = 600
SCEN_EXCERPT = 700


# 레이팅 — 상승여력 기반, 불안 신호면 Sell (사용자 정의 임계, 2026-07-21)
def _rating(upside_pct: float | None, warning: bool) -> str:
    if warning:
        return "Sell"
    if upside_pct is None:
        return "Hold"
    if upside_pct >= 50:
        return "Strong Buy"
    if upside_pct >= 15:
        return "Buy"
    return "Hold"


def _cached_upside_pct(conn, name: str | None) -> float | None:
    """저장된 업사이드 모델(models)의 기본 시나리오 상승여력 — 콜의 펀더 앵커 (①)."""
    if not name:
        return None
    row = conn.execute(
        "SELECT spec_json FROM models WHERE name LIKE ? ORDER BY updated_at DESC LIMIT 1",
        (f"{name} · %업사이드",)).fetchone()
    if not row or not row["spec_json"]:
        return None
    try:
        scens = json.loads(row["spec_json"]).get("scenarios") or []
        base = next((s for s in scens if "기본" in (s.get("name") or "")), None)
        base = base or (scens[len(scens) // 2] if scens else None)
        return base.get("upside_pct") if base else None
    except Exception:
        return None


def _signals(conn, code: str, name: str | None) -> dict:
    """콜 스코어 재료 (③) — 펀더(업사이드 캐시)·기술(RS·52주)·심리(언급 모멘텀)."""
    latest = conn.execute("SELECT max(trade_date) FROM stock_prices").fetchone()[0]
    rs = _rs_short(conn, latest).get(code) if latest else None
    r = conn.execute("""
        SELECT MIN(close) mn, MAX(close) mx,
               (SELECT close FROM stock_prices WHERE stock_code=? ORDER BY trade_date DESC LIMIT 1) cur
        FROM (SELECT close FROM stock_prices WHERE stock_code=? AND close IS NOT NULL
              ORDER BY trade_date DESC LIMIT 250)""", (code, code)).fetchone()
    pos = None
    if r and r["cur"] is not None and r["mn"] is not None and r["mx"] and r["mx"] > r["mn"]:
        pos = round((r["cur"] - r["mn"]) / (r["mx"] - r["mn"]) * 100)
    m = conn.execute("""
        SELECT SUM(CASE WHEN rd.published_at >= datetime('now','-7 days') THEN 1 ELSE 0 END) recent,
               SUM(CASE WHEN rd.published_at >= datetime('now','-14 days')
                         AND rd.published_at < datetime('now','-7 days') THEN 1 ELSE 0 END) prev
        FROM entity_links el JOIN entities e ON e.id=el.entity_id
        JOIN raw_documents rd ON rd.id=el.doc_id
        WHERE el.link_type='stock' AND e.aliases=?""", (code,)).fetchone()
    return {"rs": int(rs) if rs is not None else None, "pos_52w": pos,
            "mentions_7d": m["recent"] or 0, "mentions_prev_7d": m["prev"] or 0,
            "upside_cached": _cached_upside_pct(conn, name)}


def _latest_narr(conn, topic: str):
    return conn.execute(
        "SELECT id, topic, title, body, version FROM narratives "
        "WHERE topic=? AND COALESCE(kind,'topic')='topic' ORDER BY version DESC LIMIT 1",
        (topic,)).fetchone()


def _members_hash(members: list[tuple[str, int]]) -> str:
    return hashlib.sha256("|".join(f"{t}:{v}" for t, v in sorted(members)).encode()).hexdigest()


def _parse_json(raw: str) -> dict:
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    s, e = raw.find("{"), raw.rfind("}")
    if s < 0 or e <= s:
        raise ValueError(f"JSON 없음: {raw[:80]!r}")
    return json.loads(raw[s:e + 1])


def _anchor_line(a: dict) -> str:
    """앵커 재무를 한 줄로 (없으면 미상)."""
    def v(x, unit=""):
        return f"{x}{unit}" if x is not None else "미상"
    return (f"현재가 {v(a.get('price'))} · PER {v(a.get('per'), '배')} · "
            f"매출 {v(a.get('revenue'))} · 순이익률 {v(a.get('net_margin'), '%')} · 시총 {v(a.get('market_cap'))}")


def _synth_stock(a: dict, code: str, name: str, angles: list[dict], sig: dict) -> dict | None:
    """종목 다각도 재분석 + 콜 (sonnet, 연쇄 1콜) — 여러 내러티브 파급을 관통하는 통합 투자 포인트
    + 펀더·심리·기술 종합 콜(③). 상승여력·불안신호 → 레이팅(결정적)."""
    angle_block = "\n".join(
        f"- [{ag['narrative']}] ({ag.get('rel') or '수혜'}) {ag.get('reason') or ''}" for ag in angles)
    mom = "상승" if sig["mentions_7d"] > sig["mentions_prev_7d"] else ("둔화" if sig["mentions_7d"] < sig["mentions_prev_7d"] else "유지")
    sig_line = (f"기술: RS {sig['rs'] if sig['rs'] is not None else '미상'}(0~100 백분위)·"
                f"52주위치 {sig['pos_52w'] if sig['pos_52w'] is not None else '미상'}% · "
                f"심리: 최근7일 언급 {sig['mentions_7d']}건({mom}) · "
                f"펀더: 저장 업사이드 {sig['upside_cached'] if sig['upside_cached'] is not None else '미상'}%")
    prompt = (
        f"너는 애널리스트다. '{name}'({code})가 여러 산업 내러티브에서 각각 어떻게 영향받는지 아래에 모았다. "
        "같은 종목이라도 내러티브마다 파급 논리가 다르다 — 이 다각도를 관통하는 **하나의 통합 투자 포인트**로 "
        "종합하고(단순 나열 금지), 펀더·심리·기술을 함께 반영한 **콜**을 내라. 근거 없는 수치 창작 금지.\n"
        "JSON만 출력(코드블록·머리말 없이): "
        '{"thesis":"2~3문장 통합 논지(마크다운)","key_points":["핵심 투자 포인트 2~4개"],'
        '"risks":["리스크·무효화 조건 1~3개"],'
        '"upside_pct":"상승여력 대표값(%) 정수, 저장 업사이드가 있으면 그것을 기준으로 다각도 반영해 조정, '
        '없으면 논리적 추정(모르면 null)","warning":"불안 신호(추세 붕괴·논지 훼손·과열 위험 등)면 true, 아니면 false"}\n'
        f"[재무 앵커] {_anchor_line(a)}\n[시그널] {sig_line}\n"
        f"[내러티브별 파급]\n{angle_block}")
    try:
        d = _parse_json(_call_claude_code(prompt, model="sonnet", timeout=240))
    except Exception:
        return None
    up = d.get("upside_pct")
    try:
        up = float(up) if up is not None and str(up) != "null" else None
    except (ValueError, TypeError):
        up = None
    warning = bool(d.get("warning") is True or str(d.get("warning")).lower() == "true")
    return {"code": code, "name": name,
            "thesis": d.get("thesis") or "",
            "key_points": d.get("key_points") or [],
            "risks": d.get("risks") or [],
            "upside_pct": up, "warning": warning,
            "rating": _rating(up, warning),
            "rs": sig["rs"], "pos_52w": sig["pos_52w"]}


def _synth_report(anchor_topic: str, narr_material: list[dict], stock_blocks: list[dict]) -> dict:
    """Top-down 설득형 리포트 종합 (opus, 1콜) — 투자 포인트 → 산업 내러티브 → Numbers → 종목(레이팅)."""
    narr_block = "\n\n".join(
        f"### {m['topic']} — {m['title'] or ''}\n{(m['body'] or '')[:BODY_EXCERPT]}"
        + (f"\n[파급] {m['scenario'][:SCEN_EXCERPT]}" if m.get("scenario") else "")
        for m in narr_material)
    def _sb(s: dict) -> str:
        head = f"### {s['name']}({s['code']}) — 레이팅 {s['rating']}"
        if s.get("upside_pct") is not None:
            head += f" · 상승여력 {round(s['upside_pct'])}%"
        if s.get("rs") is not None:
            head += f" · RS {s['rs']}"
        return (f"{head}\n{s['thesis']}\n포인트: {' · '.join(s['key_points'])}\n"
                f"리스크: {' · '.join(s['risks'])}")
    stock_block = "\n\n".join(_sb(s) for s in stock_blocks) or "(분석 종목 없음)"
    prompt = (
        "너는 1인 리서치센터의 수석 애널리스트다. 아래는 공유 인과로 엮인 산업 내러티브들(참고자료)과, "
        "그것들을 관통해 이미 종합한 종목별 콜(레이팅·상승여력 포함)이다. 이를 **읽는 사람이 논지에 설득되는** "
        "Top-down 투자 리포트로 써라. 하나의 핵심 투자 포인트를 세우고, 그것을 산업 내러티브로 설명하고, "
        "Numbers로 뒷받침한 뒤, 종목으로 내려온다. 요약 나열이 아니라 하나의 설득 논리로.\n"
        "JSON만 출력(코드블록·머리말 없이): "
        '{"title": "리포트 제목(핵심 주장 한 줄)", "body": "마크다운 리포트"}\n'
        "body 구조(섹션 고정, 각 섹션 충분히 상세히):\n"
        "## 투자 포인트\n이 리포트가 주장하는 핵심 명제 1개를 2~3문장으로 또렷하게 — 왜 지금 주목해야 하는가.\n"
        "## 산업 내러티브\n그 포인트를 뒷받침하는 산업의 구조적 스토리 — 근본 동인 → 전개 갈래 → 왜 지속되는가. "
        "엮인 내러티브·파급을 하나의 흐름으로 짜라(3~5단락).\n"
        "## Numbers\n논지를 뒷받침하는 정량 근거 — 시장 규모/성장·capa/ASP/실적/밸류 등. 참고자료·시그널에 "
        "있는 수치만 사용하고 없으면 '(자료 부재)'로 정직하게. 숫자로 논지를 검증.\n"
        "## 종목\n산업 논리에서 개별 기업으로. 각 종목을 '**종목명** — 레이팅 · 상승여력' 헤더로 시작해 "
        "왜 그 레이팅인지 2~3문장. 레이팅·상승여력은 아래 제공값을 그대로 쓰고 바꾸지 마라(없는 수치 창작 금지).\n"
        "## 리스크 · 무효화\n이 논지가 틀리는 조건과 감시 신호. 타이밍은 추세추종 렌즈(RS·52주)로 별도임을 명시.\n"
        "규율: 참고자료·시그널에 없는 사실 창작 금지. **매수 일변도 금지** — 레이팅은 제공된 값(Strong Buy/Buy/"
        "Hold/Sell)을 따르고, Hold·Sell이면 그 이유를 정직하게. 범위+조건부, 단정 금지. 전체 2000~2600자. "
        "내부 코드·약어 노출 금지.\n\n"
        f"[앵커 주제] {anchor_topic}\n\n[참고 내러티브·파급]\n{narr_block}\n\n[종목별 콜]\n{stock_block}")
    d = _parse_json(_call_claude_code(prompt, model="opus", timeout=360))
    return {"title": d.get("title") or f"{anchor_topic} 통합 리포트", "body": d.get("body") or ""}


def build_report(conn, anchor_topic: str, force: bool = False) -> dict:
    """앵커 주제 → 공유 이웃 취합 → 종목 다각도 재분석 → Top-down 리포트 (연쇄 LLM, 캐시)."""
    if llm_engine() != "claude-code":
        return {"error": "LLM 엔진 없음 (ENRICH_ENGINE=claude-code 필요)"}
    anchor = _latest_narr(conn, anchor_topic)
    if not anchor:
        return {"error": f"'{anchor_topic}' 내러티브 없음 — 먼저 내러티브를 생성하세요"}

    # 1. 앵커 + 공유 이웃 (LLM 0)
    from pipeline.narrative import related_narratives
    rel = related_narratives(conn, anchor["id"]).get("related", [])
    member_narrs, seen = [dict(anchor)], {anchor_topic}
    for r in rel:
        if r["topic"] in seen:
            continue
        m = _latest_narr(conn, r["topic"])
        if m:
            member_narrs.append(dict(m)); seen.add(r["topic"])
        if len(member_narrs) > TOP_RELATED:
            break
    members = [(m["topic"], m["version"]) for m in member_narrs]
    mhash = _members_hash(members)

    # 캐시: 구성원 해시 동일 & 비-refresh → 저장분
    if not force:
        cur = conn.execute(
            "SELECT title, body, stocks_json, members_json, members_hash, created_at "
            "FROM reports WHERE anchor_topic=?", (anchor_topic,)).fetchone()
        if cur and cur["members_hash"] == mhash:
            return {"status": "ok", "title": cur["title"], "answer": cur["body"],
                    "members": json.loads(cur["members_json"] or "[]"),
                    "stocks": json.loads(cur["stocks_json"] or "[]"),
                    "cached": True, "created_at": cur["created_at"]}

    # 2. 자료 수집 + 종목별 다각도 집계 (캐시된 scenario 재사용, ② 없으면 상한 내 자동 보강)
    narr_material, stock_angles = [], {}
    augment_budget = AUGMENT_CAP
    for m in member_narrs:
        sc = conn.execute(
            "SELECT answer, beneficiaries FROM scenarios WHERE topic=?", (m["topic"],)).fetchone()
        answer = sc["answer"] if sc else None
        bens = json.loads(sc["beneficiaries"]) if (sc and sc["beneficiaries"]) else []
        if not sc and augment_budget > 0:   # ② 파급 없는 구성 내러티브 경량 보강 (best-effort)
            augment_budget -= 1
            try:
                from pipeline.scenario import build_scenario
                ev = f"{m['topic']} — {m['title']}" if m.get("title") else m["topic"]
                r = build_scenario(ev)
                if not r.get("error"):
                    answer, bens = r.get("answer"), r.get("beneficiaries") or []
            except Exception:
                pass
        narr_material.append({"topic": m["topic"], "title": m["title"], "body": m["body"],
                              "scenario": answer})
        for b in bens:
            code = b.get("stock_code")
            if not code:
                continue
            slot = stock_angles.setdefault(code, {"name": b.get("name") or code, "angles": []})
            slot["angles"].append({"narrative": m["topic"], "rel": b.get("rel"), "reason": b.get("reason")})

    # 3. 랭킹 = 등장 내러티브 수(교차 현저성)
    ranked = sorted(stock_angles.items(), key=lambda kv: -len(kv[1]["angles"]))[:TOP_STOCKS]

    # 4. 종목별 재분석 + 콜 (sonnet, 연쇄) — 펀더·심리·기술 시그널 반영(③)
    stock_blocks = []
    for code, info in ranked:
        blk = _synth_stock(_anchor(conn, code), code, info["name"], info["angles"], _signals(conn, code, info["name"]))
        if blk:
            stock_blocks.append(blk)

    # 5. 리포트 종합 (opus)
    rpt = _synth_report(anchor_topic, narr_material, stock_blocks)

    # 6. 적재
    stocks = [{"code": s["code"], "name": s["name"], "rating": s["rating"],
               "upside_pct": s["upside_pct"]} for s in stock_blocks]
    conn.execute(
        "INSERT INTO reports (anchor_topic, title, body, members_json, stocks_json, members_hash, "
        "model, created_at) VALUES (?,?,?,?,?,?,?,datetime('now')) "
        "ON CONFLICT(anchor_topic) DO UPDATE SET title=excluded.title, body=excluded.body, "
        "members_json=excluded.members_json, stocks_json=excluded.stocks_json, "
        "members_hash=excluded.members_hash, model=excluded.model, created_at=excluded.created_at",
        (anchor_topic, rpt["title"], rpt["body"], json.dumps([m["topic"] for m in member_narrs], ensure_ascii=False),
         json.dumps(stocks, ensure_ascii=False), mhash, "claude-code/opus+sonnet"))
    conn.commit()
    return {"status": "ok", "title": rpt["title"], "answer": rpt["body"],
            "members": [m["topic"] for m in member_narrs], "stocks": stocks,
            "cached": False, "created_at": None}
