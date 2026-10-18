"""시장 기대치 — 칸 구성 회사의 애널리스트 컨센서스 (docs/specs/value-chain.md §15, LLM 0).

가격을 정하는 것은 사실이 아니라 기대다. 그래서 칸마다 관측(사실) 옆에 기대를 따로 놓고, 둘의 차이와 기대의 개정을 본다.
섞지 않는다: 관측은 value_chain.read_map, 기대는 여기.

원천: yfinance(키 없음) — 미국·대만(.TW 상장 / .TWO 장외)·한국(.KS 코스피 / .KQ 코스닥)·일본(.T)을 한 원천으로 받아 비교할 수 있다.
- revenue_estimate: 이번 분기(0q)·다음 분기(+1q)·올해(0y)·내년(+1y)의 매출 추정 평균·전년 대비 성장률·애널리스트 수
- eps_trend: EPS 추정의 현재·30일 전·90일 전 → 개정 방향. 매출 추정 개정은 yfinance가 주지 않아 일별 스냅샷끼리 비교한다
칸 기대 = 구성 회사 매출 추정 합의 성장률(Σ추정 / Σ(추정/(1+g)) − 1). 회사마다 회계 분기가 달라 '이번 분기'는 근사다.
설비투자·회사채·수주잔고 칸은 매출 컨센서스가 그 칸의 기대가 아니라 비운다(하이퍼스케일러 매출 ≠ 설비투자).
"""
from __future__ import annotations

import time
from datetime import date, timedelta

PERIODS = ("0q", "+1q", "0y", "+1y")
FX_USD = {"USD": 1.0, "TWD": 1 / 32, "KRW": 1 / 1400, "JPY": 1 / 150, "EUR": 1.1}   # 가중치용 고정 환율(성장률엔 영향 없음)
SKIP_USE = {"ai", "funding", "frontier"}           # 설비투자·회사채·수주잔고 — 매출 컨센서스가 칸의 기대가 아니다
PAUSE = 0.4
# 칸 관측과 같은 사업을 보도록 기대 구성 회사를 바꾸는 칸 — 회사 전체 컨센서스가 칸 사업과 다르면 차이가 부푼다
EXP_MEMBERS = {"memory": [("000660.KS", "SK하이닉스"), ("MU", "마이크론")]}
EXP_NOTE = {"memory": "삼성전자는 스마트폰·디스플레이가 섞인 회사 전체 컨센서스라 빼고, 메모리 전업 회사(SK하이닉스·마이크론)로 기대를 계산합니다. 관측(한국 메모리 수출)과 같은 사업을 보기 위해서입니다."}


def node_symbols(conn) -> dict[str, list[tuple[str, str]]]:
    """칸 → [(yfinance 심볼 후보들 '|'로, 이름)]. 미국은 매출 관측 회사, 대만·한국은 칸에 붙은 회사"""
    from pipeline.tw_universe import COMPANIES
    from pipeline.us_fundamentals import EXTERNAL, NAMES, TARGETS
    from pipeline.value_chain import DEMANDS, NODES, US_OBS
    tw_name = {c: n for c, n, *_ in COMPANIES}
    kr = {r["stock_code"]: (r["corp_name"], r["market"]) for r in conn.execute("SELECT stock_code, corp_name, market FROM companies")}
    out: dict[str, list[tuple[str, str]]] = {}
    for key in [k for k, *_ in DEMANDS] + [n[0] for n in NODES]:
        syms: list[tuple[str, str]] = []
        if key in US_OBS and US_OBS[key][0] not in SKIP_USE:
            use = US_OBS[key][0]
            for t, metric, u in TARGETS + EXTERNAL:
                if u == use and metric == "revenue":
                    syms.append(("6146.T" if t == "DISCO" else t, NAMES.get(t, t)))
        node = next((n for n in NODES if n[0] == key), None)
        if node:
            syms += [(f"{c}.TW|{c}.TWO", tw_name.get(c, c)) for c in node[2]]
            # 시장 구분이 비거나 틀린 종목이 있어(파크시스템스·원익IPS 등) 두 접미사를 차례로 — 표시된 시장을 먼저
            syms += [(f"{c}.KQ|{c}.KS" if (kr.get(c, ("", ""))[1] or "").startswith("KOSDAQ") else f"{c}.KS|{c}.KQ", kr.get(c, (c, ""))[0]) for c in node[3]]
        if key in EXP_MEMBERS:
            syms = EXP_MEMBERS[key]
        if syms:
            out[key] = syms
    return out


def _fetch(symbol: str) -> list[dict] | None:
    """yfinance 한 심볼 → period별 행. 추정치가 없으면 None"""
    import yfinance as yf
    tk = yf.Ticker(symbol)
    rev = tk.revenue_estimate
    if rev is None or rev.empty or "avg" not in rev:
        return None
    try:
        eps = tk.eps_trend
    except Exception:  # noqa: BLE001 — EPS 추이는 없어도 매출 추정은 쓴다
        eps = None
    rows = []
    for p in PERIODS:
        if p not in rev.index:
            continue
        r = rev.loc[p]
        e = eps.loc[p] if eps is not None and not eps.empty and p in eps.index else None
        num = lambda v: float(v) if v is not None and v == v else None  # noqa: E731 — NaN 제외
        rows.append({"period": p, "rev_avg": num(r.get("avg")), "rev_growth": num(r.get("growth")),
                     "analysts": int(r["numberOfAnalysts"]) if num(r.get("numberOfAnalysts")) is not None else None,
                     "eps_avg": num(e.get("current")) if e is not None else None, "eps_30d": num(e.get("30daysAgo")) if e is not None else None,
                     "eps_90d": num(e.get("90daysAgo")) if e is not None else None, "currency": r.get("currency") or None})
    return rows or None


def collect() -> dict:
    """칸 구성 회사 컨센서스를 오늘 날짜로 스냅샷(같은 날 다시 돌리면 덮어쓴다). 대만은 .TW → .TWO 순서로 시도하고 성공한 심볼을 쓴다"""
    from database import get_connection
    conn = get_connection()
    today = date.today().isoformat()
    stored, missing, failed = 0, [], []
    try:
        seen: set[str] = set()
        for key, syms in node_symbols(conn).items():
            for cand, name in syms:
                if cand in seen:
                    continue
                seen.add(cand)
                rows, used = None, None
                for sym in cand.split("|"):
                    try:
                        rows = _fetch(sym)
                    except Exception as e:  # noqa: BLE001 — 한 심볼 실패는 남기고 다음으로
                        failed.append(f"{sym}: {type(e).__name__}")
                    time.sleep(PAUSE)
                    if rows:
                        used = sym
                        break
                if not rows:
                    missing.append(cand.split("|")[0])
                    continue
                for r in rows:
                    conn.execute("INSERT INTO consensus_snapshots (ticker, snap_date, period, rev_avg, rev_growth, analysts, eps_avg, eps_30d, eps_90d, currency) "
                                 "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ticker, snap_date, period) DO UPDATE SET rev_avg=excluded.rev_avg, "
                                 "rev_growth=excluded.rev_growth, analysts=excluded.analysts, eps_avg=excluded.eps_avg, eps_30d=excluded.eps_30d, "
                                 "eps_90d=excluded.eps_90d, currency=excluded.currency",
                                 (used, today, r["period"], r["rev_avg"], r["rev_growth"], r["analysts"], r["eps_avg"], r["eps_30d"], r["eps_90d"], r["currency"]))
                    stored += 1
                conn.commit()
    finally:
        conn.close()
    status = "error" if not stored else "partial" if failed else "ok"
    return {"status": status, "stored": stored, "missing": missing, **({"error": "; ".join(failed[:8])} if failed else {})}


def aggregate(members: list[dict], period: str) -> float | None:
    """칸 기대 성장률 = Σ추정 / Σ(추정/(1+g)) − 1 (USD 고정 환율로 맞춘 매출 가중). 성장률이 없는 회사는 뺀다"""
    cur = prev = 0.0
    for m in members:
        p = m["periods"].get(period) or {}
        g, avg = p.get("rev_growth"), p.get("rev_avg")
        if g is None or avg is None or g <= -1:
            continue
        usd = avg * FX_USD.get(m.get("currency") or "USD", 1.0)
        cur += usd
        prev += usd / (1 + g)
    return round((cur / prev - 1) * 100, 1) if prev else None


def _revision(members: list[dict], field: str) -> float | None:
    """올해(0y) EPS 추정 개정률 중앙값(%) — 현재 vs 30일·90일 전"""
    import statistics
    vals = []
    for m in members:
        p = m["periods"].get("0y") or {}
        cur, old = p.get("eps_avg"), p.get(field)
        if cur is not None and old not in (None, 0):
            vals.append((cur / old - 1) * 100 * (1 if old > 0 else -1))
    return round(statistics.median(vals), 1) if vals else None


def read(conn=None) -> dict:
    """칸별 기대 — 구성 회사 최신 스냅샷, 칸 합계 성장률(이번 분기·올해·내년), EPS 개정 중앙값, 매출 추정 30일 개정(스냅샷이 쌓인 뒤), 전망 원장"""
    from database import get_connection
    own = conn is None
    conn = conn or get_connection()
    try:
        snap = conn.execute("SELECT MAX(snap_date) FROM consensus_snapshots").fetchone()[0]
        if not snap:
            return {"as_of": None, "nodes": {}}
        month_ago = conn.execute("SELECT MAX(snap_date) FROM consensus_snapshots WHERE snap_date <= ?",
                                 ((date.fromisoformat(snap) - timedelta(days=28)).isoformat(),)).fetchone()[0]
        latest: dict[str, dict] = {}
        for r in conn.execute("SELECT s.* FROM consensus_snapshots s JOIN (SELECT ticker, MAX(snap_date) d FROM consensus_snapshots "
                              "GROUP BY ticker) m ON m.ticker=s.ticker AND m.d=s.snap_date"):
            t = latest.setdefault(r["ticker"], {"symbol": r["ticker"], "currency": r["currency"], "snap_date": r["snap_date"], "periods": {}})
            t["periods"][r["period"]] = {k: r[k] for k in ("rev_avg", "rev_growth", "analysts", "eps_avg", "eps_30d", "eps_90d")}
        old = {(r["ticker"], r["period"]): r["rev_avg"] for r in conn.execute(
            "SELECT ticker, period, rev_avg FROM consensus_snapshots WHERE snap_date=?", (month_ago,))} if month_ago and month_ago < snap else {}
        claims: dict[str, list[dict]] = {}
        for r in conn.execute("SELECT * FROM expectation_claims WHERE node_key != '' ORDER BY published_at DESC"):
            claims.setdefault(r["node_key"], []).append({k: r[k] for k in ("source", "source_org", "published_at", "subject", "metric", "target_period",
                                                                              "value_low", "value_high", "unit", "direction", "quote", "url")})
        nodes = {}
        for key, syms in node_symbols(conn).items():
            members = []
            for cand, name in syms:
                sym = next((s for s in cand.split("|") if s in latest), None)
                if sym:
                    m = {**latest[sym], "name": name}
                    o, c = old.get((sym, "0y")), m["periods"].get("0y", {}).get("rev_avg")
                    m["rev_revision_30d"] = round((c / o - 1) * 100, 1) if o and c else None
                    members.append(m)
            revs = [m["rev_revision_30d"] for m in members if m["rev_revision_30d"] is not None]
            nodes[key] = {"members": members, "coverage": f"{len(members)}/{len(syms)}",
                          "exp_0q": aggregate(members, "0q"), "exp_0y": aggregate(members, "0y"), "exp_1y": aggregate(members, "+1y"),
                          "eps_rev_30d": _revision(members, "eps_30d"), "eps_rev_90d": _revision(members, "eps_90d"),
                          "rev_rev_30d": round(sum(revs) / len(revs), 1) if revs else None,
                          "claims": claims.get(key, [])[:8], "note": EXP_NOTE.get(key)}
        for key, cl in claims.items():                 # 컨센서스 회사가 없는 칸에도 전망 원장은 보인다
            nodes.setdefault(key, {"members": [], "coverage": "0/0", "exp_0q": None, "exp_0y": None, "exp_1y": None,
                                   "eps_rev_30d": None, "eps_rev_90d": None, "rev_rev_30d": None, "claims": cl[:8]})
        return {"as_of": snap, "revision_base": month_ago if old else None, "nodes": nodes}
    finally:
        if own:
            conn.close()


GAP_PP = 15.0   # 관측과 기대(이번 분기)의 차이가 이보다 크면 목록에 올린다


def with_observed(vmap: dict | None = None) -> dict:
    """기대 + 관측 나란히 — 칸 관측(최근 3개월·최신 분기 YoY)과 기대(이번 분기 성장률)의 차이(%p).
    앞선 칸 = 관측이 기대보다 크게 높다(추정이 따라 올라갈 여지), 뒤처진 칸 = 기대가 관측보다 높다(실망 위험).
    대리 관측 칸(한국 업계 수출)은 관측이 붙은 종목의 매출이 아니라 표시만 하고 목록 판정에는 쓰지 않는다"""
    from pipeline.value_chain import obs_kind, read_map
    vmap = vmap or read_map()
    exp = read()
    obs = {n["key"]: n for n in vmap["nodes"]} | {d["key"]: d for d in vmap["demands"]}
    ahead, behind = [], []
    for key, n in exp["nodes"].items():
        o = obs.get(key, {})
        n["name"] = o.get("name", key)
        n["observed"] = o.get("yoy_3m")
        n["observed_period"] = o.get("period")
        n["obs_kind"] = obs_kind(key) if key in obs else None
        n["gap_pp"] = round(n["observed"] - n["exp_0q"], 1) if n["observed"] is not None and n["exp_0q"] is not None else None
        if n["gap_pp"] is None or n["obs_kind"] == "proxy":
            continue
        row = {"key": key, "name": n["name"], "observed": n["observed"], "exp_0q": n["exp_0q"], "gap_pp": n["gap_pp"],
               "eps_rev_30d": n["eps_rev_30d"], "eps_rev_90d": n["eps_rev_90d"]}
        if n["gap_pp"] >= GAP_PP:
            ahead.append(row)
        elif n["gap_pp"] <= -GAP_PP:
            behind.append(row)
    return {**exp, "gap_pp": GAP_PP, "ahead": sorted(ahead, key=lambda r: -r["gap_pp"]), "behind": sorted(behind, key=lambda r: r["gap_pp"])}
