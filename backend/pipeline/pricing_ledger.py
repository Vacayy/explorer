"""시장 프라이싱 원장 (docs/specs/pricing-ledger.md) — 시장이 지금 무엇을 가격에 반영하고 있나.

이야기 층: 매일 미국장 브리핑에서 '시장이 전제로 삼는 기대'를 LLM 1회로 뽑아 기존 전제에 잇는다(pricing_claims·pricing_observations).
가격 층: 이미 수집 중인 market_indicators 계열의 지금 값·1주·4주 변화(LLM 0).
"""
import json
import os

from database import get_connection
from pipeline import llm

MODEL = os.getenv("PRICING_MODEL", "sonnet")
THEMES = ("rates", "inflation", "growth", "credit", "geopolitics", "energy", "ai", "sector", "fx", "policy", "other")
STANCES = ("present", "stronger", "weaker", "contested")
LOOKBACK_DAYS = 45      # 추출 때 보여 줄 기존 전제 범위
RECENT = 5              # '이번 주' = 최근 5개 브리핑일
FADE_WINDOW = 20        # 사라짐 판정: 그 전 20개 브리핑일 안 3회 이상 관측
MAX_PER_DAY = 6

# 가격 층 — (지표 키, 라벨, 단위, 변화 표시 방식)
PRICE = [
    ("risk_us2y", "미 2년 금리(정책 경로)", "%", "bp"),
    ("risk_us10y", "미 10년 금리", "%", "bp"),
    ("era_t5yifr", "5년 뒤 5년 기대인플레", "%", "bp"),
    ("era_tp10", "10년 기간 프리미엄", "%", "bp"),
    ("risk_hy", "하이일드 스프레드", "%", "bp"),
    ("risk_vix", "VIX", "", "pt"),
    ("macro_oil", "유가(WTI)", "$", "pct"),
    ("era_gold", "금", "$", "pct"),
    ("era_dxy", "달러지수", "", "pct"),
]
THEME_PRICE = {"rates": ["risk_us2y", "risk_us10y"], "policy": ["risk_us2y", "era_tp10"], "inflation": ["era_t5yifr"],
               "credit": ["risk_hy"], "geopolitics": ["macro_oil", "era_gold"], "energy": ["macro_oil"], "fx": ["era_dxy"],
               "growth": ["risk_us10y", "risk_vix"]}

SYSTEM = """너는 미국장 브리핑을 읽고 '시장이 지금 가격에 반영하고 있는 전제'를 기록하는 분석가다.
전제 = 사건이 아니라 시장이 믿고 움직이는 기대다. 예: "연준은 다음 FOMC에서 금리를 동결한다", "유가에 중동 확전 위험 프리미엄이 붙어 있다",
"AI 인프라 투자는 계속 늘어난다". 나쁜 예: "룰라가 재선됐다"(사건), "브렌트유가 117달러를 넘었다"(수치).
규칙:
- 브리핑에 근거가 있는 것만. 지어내지 않는다.
- 먼저 기존 전제 목록에서 같은 전제를 찾는다. 같은 뜻이면 반드시 그 claim_id로 관측을 남긴다(새로 만들지 않는다).
- stance: present(그대로 유지) · stronger(오늘 강해짐) · weaker(약해짐) · contested(반론·반대 근거 등장).
- 새 전제 문장은 한국어 한 문장, 날짜·구체 수치를 넣지 않아 다른 날에도 그대로 쓸 수 있게.
- theme: rates·inflation·growth·credit·geopolitics·energy·ai·sector·fx·policy·other 중 하나.
- evidence는 브리핑에서 근거가 된 내용 한 문장(수치 포함 가능), sources는 브리핑 출처 번호 [n] 목록.
- 관측과 새 전제를 합쳐 최대 6개. 시장 전체에 중요한 것부터.
출력은 JSON 한 개만:
{"observations":[{"claim_id":1,"stance":"present","evidence":"...","sources":[1,2]}],
 "new":[{"statement":"...","theme":"rates","evidence":"...","sources":[3]}]}"""


# ── 추출 ────────────────────────────────────────────────────────────────────

def _briefing(conn, trade_date):
    r = conn.execute("SELECT trade_date, signature, synthesis_json FROM us_briefings WHERE trade_date=?", (trade_date,)).fetchone()
    if not r:
        return None
    return r["trade_date"], r["signature"], json.loads(r["synthesis_json"] or "{}")


def _input_text(syn: dict) -> str:
    parts = []
    # 브리핑 형식이 바뀌어 왔다(mood → drivers·flow → key_points·sources). 있는 키만 쓴다
    for key, label in (("index_summary", "지수"), ("mood", "분위기"), ("drivers", "동인"), ("flow", "수급"), ("issues", "개별 이슈")):
        if isinstance(syn.get(key), str) and syn[key].strip():
            parts.append(f"## {label}\n{syn[key]}")
    for key, label in (("key_points", "핵심 포인트"), ("share_candidates", "시장 내러티브")):
        if syn.get(key):
            parts.append(f"## {label}\n" + "\n".join(f"- {p}" for p in syn[key] if isinstance(p, str)))
    if syn.get("sources"):
        parts.append("## 출처\n" + "\n".join(f"[{s.get('n')}] {s.get('publisher', '')} — {s.get('title', '')}" for s in syn["sources"]))
    return "\n\n".join(parts)


def _active_claims(conn, trade_date):
    return [dict(r) for r in conn.execute(
        "SELECT id, statement, theme, last_seen FROM pricing_claims WHERE last_seen >= date(?, ?) AND first_seen < ? ORDER BY last_seen DESC",
        (trade_date, f"-{LOOKBACK_DAYS} days", trade_date))]


def _sources(syn: dict, ns) -> list[dict]:
    by = {s.get("n"): s for s in syn.get("sources") or []}
    out = []
    for n in ns or []:
        s = by.get(n)
        if s:
            out.append({k: s.get(k) for k in ("publisher", "title", "url", "doc_id")})
    return out


def extract_day(trade_date: str, force: bool = False) -> dict:
    """브리핑 하루 → 전제 관측·새 전제. 브리핑 signature가 같으면 건너뛴다."""
    conn = get_connection()
    try:
        b = _briefing(conn, trade_date)
        if not b:
            return {"trade_date": trade_date, "status": "no_briefing"}
        _, signature, syn = b
        done = conn.execute("SELECT signature FROM pricing_days WHERE trade_date=?", (trade_date,)).fetchone()
        if done and done["signature"] == signature and not force:
            return {"trade_date": trade_date, "status": "skip"}
        claims = _active_claims(conn, trade_date)
    finally:
        conn.close()
    text = _input_text(syn)
    if not text.strip():
        return {"trade_date": trade_date, "status": "empty"}
    listing = "\n".join(f"{c['id']}. [{c['theme']}] {c['statement']}" for c in claims) or "(아직 없음)"
    prompt = f"# 기존 전제 목록(id. [테마] 문장)\n{listing}\n\n# {trade_date} 미국장 브리핑\n{text}"
    res = llm.run(prompt, system=SYSTEM, model=MODEL, effort="low", timeout=240, job="pricing.extract")
    data = llm.extract_json(res.text) or {}
    known = {c["id"] for c in claims}
    obs = [o for o in data.get("observations") or [] if o.get("claim_id") in known and o.get("stance") in STANCES][:MAX_PER_DAY]
    new = [x for x in data.get("new") or [] if (x.get("statement") or "").strip()][:max(0, MAX_PER_DAY - len(obs))]
    conn = get_connection()
    try:
        conn.execute("DELETE FROM pricing_observations WHERE trade_date=?", (trade_date,))   # force 재추출 시 그날 관측을 다시 쓴다
        for o in obs:
            conn.execute("INSERT OR REPLACE INTO pricing_observations (trade_date, claim_id, stance, evidence, sources_json) VALUES (?,?,?,?,?)",
                         (trade_date, o["claim_id"], o["stance"], (o.get("evidence") or "")[:400], json.dumps(_sources(syn, o.get("sources")), ensure_ascii=False)))
        for x in new:
            theme = x.get("theme") if x.get("theme") in THEMES else "other"
            cur = conn.execute("INSERT INTO pricing_claims (statement, theme, first_seen, last_seen) VALUES (?,?,?,?)",
                               (x["statement"].strip()[:200], theme, trade_date, trade_date))
            conn.execute("INSERT INTO pricing_observations (trade_date, claim_id, stance, evidence, sources_json) VALUES (?,?,?,?,?)",
                         (trade_date, cur.lastrowid, "present", (x.get("evidence") or "")[:400], json.dumps(_sources(syn, x.get("sources")), ensure_ascii=False)))
        # first_seen·last_seen은 관측에서 다시 잰다(소급·재추출에도 맞게)
        conn.execute("""UPDATE pricing_claims SET first_seen=(SELECT min(trade_date) FROM pricing_observations o WHERE o.claim_id=pricing_claims.id),
                        last_seen=(SELECT max(trade_date) FROM pricing_observations o WHERE o.claim_id=pricing_claims.id)
                        WHERE id IN (SELECT claim_id FROM pricing_observations)""")
        conn.execute("DELETE FROM pricing_claims WHERE id NOT IN (SELECT claim_id FROM pricing_observations)")   # 재추출로 관측을 잃은 전제
        conn.execute("INSERT OR REPLACE INTO pricing_days (trade_date, signature, model, new_claims, observed) VALUES (?,?,?,?,?)",
                     (trade_date, signature, res.label, len(new), len(obs)))
        conn.commit()
    finally:
        conn.close()
    return {"trade_date": trade_date, "status": "ok", "observed": len(obs), "new": len(new)}


def extract_pending(limit: int | None = None) -> list[dict]:
    """아직 추출하지 않았거나 브리핑이 바뀐 날을 오름차순으로(소급 시 그날까지의 전제만 보인다)."""
    conn = get_connection()
    try:
        days = [r[0] for r in conn.execute(
            "SELECT b.trade_date FROM us_briefings b LEFT JOIN pricing_days p ON p.trade_date=b.trade_date "
            "WHERE p.trade_date IS NULL OR p.signature != b.signature ORDER BY b.trade_date")]
    finally:
        conn.close()
    out = []
    for d in days[:limit] if limit else days:
        try:
            out.append(extract_day(d))
        except Exception as exc:  # noqa: BLE001 — 날짜별 보고, 다음 날 계속
            out.append({"trade_date": d, "status": "error", "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
    return out


# ── 읽기 ────────────────────────────────────────────────────────────────────

def _price_layer(conn, as_of: str | None) -> list[dict]:
    from pipeline.era import _at, _series
    from datetime import date, timedelta
    out = []
    for key, label, unit, mode in PRICE:
        s = _series(conn, key)
        if not s:
            out.append({"key": key, "label": label, "unit": unit, "value": None, "as_of": None, "chg_1w": None, "chg_4w": None, "mode": mode})
            continue
        d, v = s[-1]
        def chg(days):
            old = _at(s, (date.fromisoformat(d) - timedelta(days=days)).isoformat())
            if old is None:
                return None
            if mode == "bp":
                return round((v - old) * 100, 1)
            if mode == "pct":
                return round((v / old - 1) * 100, 2) if old else None
            return round(v - old, 2)
        out.append({"key": key, "label": label, "unit": unit, "value": round(v, 2), "as_of": d, "chg_1w": chg(7), "chg_4w": chg(28), "mode": mode})
    return out


def read(weeks: int = 8) -> dict:
    conn = get_connection()
    try:
        days = [r[0] for r in conn.execute("SELECT trade_date FROM us_briefings ORDER BY trade_date DESC LIMIT ?", (weeks * 5,))][::-1]
        extracted = {r[0] for r in conn.execute("SELECT trade_date FROM pricing_days")}
        pending = conn.execute("SELECT COUNT(*) FROM us_briefings b LEFT JOIN pricing_days p ON p.trade_date=b.trade_date "
                               "WHERE p.trade_date IS NULL OR p.signature != b.signature").fetchone()[0]
        lo = days[0] if days else "9999"
        claims = {r["id"]: {**dict(r), "obs": []} for r in conn.execute(
            "SELECT id, statement, theme, first_seen, last_seen FROM pricing_claims WHERE last_seen >= ?", (lo,))}
        for r in conn.execute("SELECT trade_date, claim_id, stance, evidence, sources_json FROM pricing_observations WHERE trade_date >= ? ORDER BY trade_date", (lo,)):
            if r["claim_id"] in claims:
                claims[r["claim_id"]]["obs"].append({"date": r["trade_date"], "stance": r["stance"], "evidence": r["evidence"],
                                                     "sources": json.loads(r["sources_json"] or "[]")})
        prices = _price_layer(conn, days[-1] if days else None)
    finally:
        conn.close()
    recent = set(days[-RECENT:])
    before = set(days[-(RECENT + FADE_WINDOW):-RECENT])
    items = []
    for c in claims.values():
        seen = [o["date"] for o in c["obs"]]
        rec = [o for o in c["obs"] if o["date"] in recent]
        if c["first_seen"] in recent:
            status = "new"
        elif any(o["stance"] == "stronger" for o in rec):
            status = "stronger"
        elif any(o["stance"] in ("weaker", "contested") for o in rec):
            status = "weaker"
        elif not rec and sum(d in before for d in seen) >= 3:
            status = "faded"
        elif rec:
            status = "ongoing"
        else:
            status = "dormant"
        last = c["obs"][-1] if c["obs"] else None
        items.append({"id": c["id"], "statement": c["statement"], "theme": c["theme"], "first_seen": c["first_seen"], "last_seen": c["last_seen"],
                      "days_seen": len(seen), "status": status, "dates": [[o["date"], o["stance"]] for o in c["obs"]],
                      "latest": last, "related": THEME_PRICE.get(c["theme"], [])})
    order = {"new": 0, "stronger": 1, "weaker": 2, "faded": 3, "ongoing": 4, "dormant": 5}
    items.sort(key=lambda x: (order[x["status"]], -x["days_seen"]))
    summary = {k: [i["statement"] for i in items if i["status"] == k] for k in ("new", "stronger", "weaker", "faded")}
    return {"days": days, "as_of": days[-1] if days else None, "extracted_days": len(extracted & set(days)), "pending": pending,
            "prices": prices, "claims": items, "summary": summary}


def brief(weeks: int = 4) -> dict:
    """대화 도구·해설용 요약 — 날짜 배열·출처를 빼고 상태별 전제와 가격 변화만."""
    d = read(weeks)
    keep = [c for c in d["claims"] if c["status"] != "dormant"][:14]
    return {"as_of": d["as_of"], "summary": d["summary"],
            "claims": [{"statement": c["statement"], "theme": c["theme"], "status": c["status"], "first_seen": c["first_seen"],
                        "last_seen": c["last_seen"], "days_seen": c["days_seen"], "latest_evidence": (c["latest"] or {}).get("evidence")} for c in keep],
            "prices": [{k: p[k] for k in ("label", "value", "unit", "chg_1w", "chg_4w", "mode")} for p in d["prices"]]}

