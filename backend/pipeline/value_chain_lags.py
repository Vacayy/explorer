"""밸류체인 시차 측정 — 지도(pipeline/value_chain)의 엣지마다 대만 월매출로 선행 시차와 강도를 잰다 (LLM 0).

각 노드 = 소속 대만 회사 월매출 합. 신호는 YoY의 월간 변화(Δ)다 — YoY 수준끼리 비교하면 같은 사이클이라는
이유만으로 상관이 부푼다(D-250의 해운 사례). Δ끼리 맞추면 '가속·감속의 시점'이 같은가를 본다.
두 신호로 잰다: 3개월 YoY의 Δ(매끄럽지만 3개월 창이 겹쳐 이웃 달끼리 닮는다)와 월 YoY의 Δ(겹침 없음, 잡음 큼).
lag = k(>0)는 공급 쪽(from)이 k개월 앞선다는 뜻, k<0은 수요 쪽(to)이 앞선다는 뜻이다.

판정 기준은 위약(placebo)으로 보정한다: 공급 관계가 없는 해운(컨테이너 3사·벌크 3사)을 각 노드와 똑같이 재서
그 최댓값 상관 분포의 상위 5%를 넘어야 '통과'다. 고정 기준(2.5/√n)은 겹침 때문에 위약 쌍의 34%를 통과시켰다(2026-10-18).
두 신호 모두 통과 = 확인, 하나만 = 부분, 둘 다 못 넘음 = 미확인. 방향은 사업 구조로 이미 정했고 여기서는 시차·강도만 잰다.
"""
from __future__ import annotations

import math

MAX_LAG = 6
MIN_PAIRS = 18


def node_yoy3m(conn, codes: list[str]) -> dict[str, float]:
    """노드(회사 묶음) 합계의 3개월 YoY(%) — 모든 회사가 있는 달만"""
    ph = ",".join("?" * len(codes))
    rows = conn.execute(f"SELECT ym, SUM(revenue) r, SUM(last_year) ly, COUNT(*) n FROM tw_monthly_revenue "
                        f"WHERE code IN ({ph}) GROUP BY ym ORDER BY ym", codes).fetchall()
    months = [(r["ym"], r["r"], r["ly"]) for r in rows if r["n"] == len(codes) and r["ly"]]
    out = {}
    for i in range(2, len(months)):
        win = months[i - 2:i + 1]
        out[months[i][0]] = (sum(m[1] for m in win) / sum(m[2] for m in win) - 1) * 100
    return out


def node_yoy(conn, codes: list[str]) -> dict[str, float]:
    """노드 합계의 월 YoY(%)"""
    ph = ",".join("?" * len(codes))
    rows = conn.execute(f"SELECT ym, SUM(revenue) r, SUM(last_year) ly, COUNT(*) n FROM tw_monthly_revenue "
                        f"WHERE code IN ({ph}) GROUP BY ym ORDER BY ym", codes).fetchall()
    return {r["ym"]: (r["r"] / r["ly"] - 1) * 100 for r in rows if r["n"] == len(codes) and r["ly"]}


def kr_monthly(conn, hs: list[str]) -> dict[str, float]:
    """한국 수출(USD) 품목 합 — 모든 품목이 있는 달만"""
    agg: dict[str, list[float]] = {}
    for r in conn.execute(f"SELECT period, export_usd FROM trade_stats WHERE hs_code IN ({','.join('?' * len(hs))}) "
                          "AND export_usd IS NOT NULL", hs):
        agg.setdefault(r["period"], []).append(r["export_usd"])
    return {p: sum(v) for p, v in sorted(agg.items()) if len(v) == len(hs)}


def kr_yoy3m(conn, hs: list[str]) -> dict[str, float]:
    """한국 수출 칸(KR_OBS)의 3개월 YoY — 대만 노드와 같은 신호로 시차를 잰다(2026-10-18 메모리 칸 관측 교체)"""
    return _yoy3m_of(kr_monthly(conn, hs))


def kr_yoy(conn, hs: list[str]) -> dict[str, float]:
    return _yoy_of(kr_monthly(conn, hs))


def kr_quarterly_yoy(conn, hs: list[str]) -> dict[str, float]:
    return _quarterly_of(kr_monthly(conn, hs))


def ext_yoy3m(conn, series: str) -> dict[str, float]:
    """외부 월간 시계열이 주 관측인 칸(EXT_OBS — 중국 세관·일본 무역통계)"""
    from pipeline.ext_series import read
    return _yoy3m_of(read(conn, series))


def ext_yoy(conn, series: str) -> dict[str, float]:
    from pipeline.ext_series import read
    return _yoy_of(read(conn, series))


def ext_quarterly_yoy(conn, series: str) -> dict[str, float]:
    from pipeline.ext_series import read
    return _quarterly_of(read(conn, series))


def _yoy3m_of(m: dict[str, float]) -> dict[str, float]:
    out = {}
    for p in m:
        cur = [_shift_ym(p, -i) for i in range(3)]
        prev = [_shift_ym(c, -12) for c in cur]
        if all(c in m for c in cur + prev) and sum(m[c] for c in prev):
            out[p] = (sum(m[c] for c in cur) / sum(m[c] for c in prev) - 1) * 100
    return out


def _yoy_of(m: dict[str, float]) -> dict[str, float]:
    return {p: (v / m[_shift_ym(p, -12)] - 1) * 100 for p, v in m.items() if m.get(_shift_ym(p, -12))}


def _quarterly_of(m: dict[str, float]) -> dict[str, float]:
    q: dict[str, list[str]] = {}
    for p in m:
        q.setdefault(f"{p[:4]}-{((int(p[5:]) - 1) // 3 + 1) * 3:02d}", []).append(p)
    out = {}
    for k, ps in q.items():
        prev = [_shift_ym(p, -12) for p in ps]
        if len(ps) == 3 and all(p in m for p in prev) and sum(m[p] for p in prev):
            out[k] = (sum(m[p] for p in ps) / sum(m[p] for p in prev) - 1) * 100
    return dict(sorted(out.items()))


PLACEBO = (["2603", "2609", "2615"], ["2637", "2606", "2605"])   # 컨테이너·벌크 해운 — 반도체·IT 공급 관계 없음
SIGNALS = (("yoy3m", node_yoy3m), ("yoy", node_yoy))


def _delta(series: dict[str, float]) -> dict[str, float]:
    keys = sorted(series)
    return {k: series[k] - series[p] for p, k in zip(keys, keys[1:])}


def _shift_ym(ym: str, months: int) -> str:
    y, m = int(ym[:4]), int(ym[5:])
    idx = y * 12 + (m - 1) + months
    return f"{idx // 12}-{idx % 12 + 1:02d}"


def _corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else None


def cross_lag(up: dict[str, float], down: dict[str, float]) -> dict:
    """lag별 상관 — lag=k면 up의 t−k 월과 down의 t 월을 짝짓는다(공급 쪽이 k개월 앞섬)"""
    du, dd = _delta(up), _delta(down)
    by = {}
    for k in range(-MAX_LAG, MAX_LAG + 1):
        pairs = [(du[_shift_ym(t, -k)], v) for t, v in dd.items() if _shift_ym(t, -k) in du]
        if len(pairs) >= MIN_PAIRS:
            c = _corr([a for a, _ in pairs], [b for _, b in pairs])
            if c is not None:
                by[k] = {"corr": round(c, 2), "n": len(pairs)}
    if not by:
        return {"best_lag": None, "corr": None, "n": 0, "by_lag": {}}
    best = max(by, key=lambda k: by[k]["corr"])
    return {"best_lag": best, "corr": by[best]["corr"], "n": by[best]["n"],
            "by_lag": {str(k): v["corr"] for k, v in sorted(by.items())}}


def placebo_threshold(conn, fn, node_codes: list[list[str]], q: float = 0.95) -> float:
    """해운 묶음 × 각 노드(양방향)의 최댓값 상관 분포 상위 q"""
    vals = []
    for grp in PLACEBO:
        p = fn(conn, grp)
        for codes in node_codes:
            s = fn(conn, codes)
            vals += [x for x in (cross_lag(p, s)["corr"], cross_lag(s, p)["corr"]) if x is not None]
    vals.sort()
    return round(vals[min(len(vals) - 1, int(len(vals) * q))], 2) if vals else 1.0


# 한국 수출 칸이 걸린 쌍은 같은 통관 통계의 공통 요인(영업일 수 등)이 상관을 부풀릴 수 있다 —
# 반도체와 무관한 한국 수출 품목을 위약으로 따로 재서, 대만 위약 기준과 둘 중 높은 쪽을 쓴다(2026-10-18)
KR_PLACEBO = (["8703"], ["1902301010"], ["2402201000"], ["4011101000"])   # 승용차·라면·담배·타이어


def placebo_threshold_kr(conn, name: str, series_list: list[dict], q: float = 0.95) -> float:
    fn = {"yoy3m": kr_yoy3m, "yoy": kr_yoy}[name]
    vals = []
    for hs in KR_PLACEBO:
        p = fn(conn, hs)
        for s in series_list:
            if p and s:
                vals += [x for x in (cross_lag(p, s)["corr"], cross_lag(s, p)["corr"]) if x is not None]
    vals.sort()
    return round(vals[min(len(vals) - 1, int(len(vals) * q))], 2) if vals else 1.0


# ── 분기 신호: 미국 분기 실적으로 관측하는 칸(AI 수요·가속기·스마트폰)이 걸린 엣지 ──
MAX_LAG_Q = 2
MIN_PAIRS_Q = 12


def tw_quarterly_yoy(conn, codes: list[str]) -> dict[str, float]:
    """대만 회사 묶음의 달력 분기 매출 YoY(%) — 분기 3개월이 모두 있고 전년 값이 있을 때"""
    ph = ",".join("?" * len(codes))
    rows = conn.execute(f"SELECT ym, SUM(revenue) r, SUM(last_year) ly, COUNT(*) n FROM tw_monthly_revenue "
                        f"WHERE code IN ({ph}) GROUP BY ym", codes).fetchall()
    q: dict[str, list] = {}
    for r in rows:
        if r["n"] != len(codes) or not r["ly"]:
            continue
        y, m = int(r["ym"][:4]), int(r["ym"][5:])
        q.setdefault(f"{y}-{((m - 1) // 3 + 1) * 3:02d}", []).append((r["r"], r["ly"]))
    return {k: (sum(a for a, _ in v) / sum(b for _, b in v) - 1) * 100 for k, v in sorted(q.items()) if len(v) == 3}


def node_quarterly(conn, key: str) -> dict[str, float]:
    from pipeline.us_fundamentals import demand_series
    from pipeline.value_chain import EXT_OBS, KR_OBS, NODE_BY_KEY, US_OBS
    if key in US_OBS:
        return demand_series(conn, US_OBS[key][0])
    if key in KR_OBS:
        return kr_quarterly_yoy(conn, KR_OBS[key][0])
    if key in EXT_OBS:
        return ext_quarterly_yoy(conn, EXT_OBS[key][0])
    codes = NODE_BY_KEY[key][2] if key in NODE_BY_KEY else []
    return tw_quarterly_yoy(conn, codes) if codes else {}


def cross_lag_q(up: dict[str, float], down: dict[str, float]) -> dict:
    """분기 YoY Δ끼리 시차(분기) −2~+2 — lag=k면 up의 t−k분기와 down의 t분기"""
    du, dd = _delta(up), _delta(down)
    by = {}
    for k in range(-MAX_LAG_Q, MAX_LAG_Q + 1):
        pairs = [(du[_shift_ym(t, -3 * k)], v) for t, v in dd.items() if _shift_ym(t, -3 * k) in du]
        if len(pairs) >= MIN_PAIRS_Q:
            c = _corr([a for a, _ in pairs], [b for _, b in pairs])
            if c is not None:
                by[k] = {"corr": round(c, 2), "n": len(pairs)}
    if not by:
        return {"best_lag": None, "corr": None, "n": 0, "by_lag": {}}
    best = max(by, key=lambda k: by[k]["corr"])
    return {"best_lag": best * 3, "corr": by[best]["corr"], "n": by[best]["n"],        # 시차는 개월로 통일
            "by_lag": {str(k * 3): v["corr"] for k, v in sorted(by.items())}}


def placebo_threshold_q(conn, keys: list[str], q: float = 0.95) -> float:
    vals = []
    for grp in PLACEBO:
        p = tw_quarterly_yoy(conn, grp)
        for k in keys:
            s = node_quarterly(conn, k)
            if s:
                vals += [x for x in (cross_lag_q(p, s)["corr"], cross_lag_q(s, p)["corr"]) if x is not None]
    vals.sort()
    return round(vals[min(len(vals) - 1, int(len(vals) * q))], 2) if vals else 1.0


_memo: dict[tuple, dict] = {}


def measure_all() -> dict:
    """엣지마다 두 신호의 최적 시차·상관과 위약 보정 판정. 반환 {thresholds, edges}. 대만 수집 시각이 같으면 캐시"""
    from database import get_connection
    from pipeline.value_chain import EDGES, EXT_OBS, KR_OBS, NODE_BY_KEY, US_OBS
    conn = get_connection()
    stamp = tuple(conn.execute("SELECT MAX(ym), MAX(fetched_at) FROM tw_monthly_revenue").fetchone()) + \
        tuple(conn.execute("SELECT MAX(q), MAX(fetched_at) FROM us_quarterly").fetchone()) + \
        tuple(conn.execute("SELECT MAX(period), MAX(fetched_at) FROM trade_stats").fetchone()) + \
        tuple(conn.execute("SELECT MAX(period), MAX(fetched_at) FROM ext_series").fetchone())
    if stamp in _memo:
        conn.close()
        return _memo[stamp]
    try:
        observed = [n[2] for n in NODE_BY_KEY.values() if n[2]]
        thresholds = {name: placebo_threshold(conn, fn, observed) for name, fn in SIGNALS}
        q_keys = [k for k in NODE_BY_KEY if NODE_BY_KEY[k][2] or k in US_OBS] + [k for k in US_OBS if k not in NODE_BY_KEY]
        thresholds["yoy_q"] = placebo_threshold_q(conn, q_keys)
        cache: dict[tuple, dict] = {}

        kr_fn = {"yoy3m": kr_yoy3m, "yoy": kr_yoy}
        ext_fn = {"yoy3m": ext_yoy3m, "yoy": ext_yoy}
        for name, fn in SIGNALS:                       # 한국 위약 — 모든 관측 칸(대만·한국 수출) 시계열과 맞대 본다
            all_series = [fn(conn, c) for c in observed] + [kr_fn[name](conn, v[0]) for v in KR_OBS.values()]
            thresholds[f"{name}_kr"] = max(thresholds[name], placebo_threshold_kr(conn, name, all_series))

        def series(name, fn, key):
            if (name, key) not in cache:
                if key in KR_OBS:                      # 한국 수출로 관측하는 칸 — 같은 신호를 수출 시계열로
                    cache[(name, key)] = kr_fn[name](conn, KR_OBS[key][0])
                elif key in EXT_OBS:                   # 외부 월간 시계열 칸 — 대만 위약 기준을 그대로 쓴다
                    cache[(name, key)] = ext_fn[name](conn, EXT_OBS[key][0])
                else:
                    codes = NODE_BY_KEY[key][2] if key in NODE_BY_KEY else []
                    cache[(name, key)] = fn(conn, codes) if codes else {}
            return cache[(name, key)]

        edges = []
        for a, b, kind, why in EDGES:
            row = {"from": a, "to": b, "kind": kind, "reason": why, "signals": {}}
            if a in US_OBS or b in US_OBS:                 # 분기 관측 칸이 걸린 엣지 — 분기 신호 하나로
                up, down = node_quarterly(conn, a), node_quarterly(conn, b)
                if up and down:
                    r = cross_lag_q(up, down)
                    r["passed"] = r["corr"] is not None and r["corr"] > thresholds["yoy_q"]
                    row["signals"]["yoy_q"] = r
                    row["verdict"] = "확인" if r["passed"] else ("미확인" if r["corr"] is not None else "관측 불가")
                    row["lag"], row["lag_consistent"] = r["best_lag"], True
                else:
                    row["verdict"] = "관측 불가"
                edges.append(row)
                continue
            for name, fn in SIGNALS:
                up, down = series(name, fn, a), series(name, fn, b)
                if up and down:
                    r = cross_lag(up, down)
                    th = thresholds[f"{name}_kr"] if (a in KR_OBS or b in KR_OBS) else thresholds[name]
                    r["passed"] = r["corr"] is not None and r["corr"] > th
                    row["signals"][name] = r
            sig = row["signals"]
            if not sig:
                row["verdict"] = "관측 불가"
            else:
                passed = [k for k, v in sig.items() if v["passed"]]
                row["verdict"] = "확인" if len(passed) == len(SIGNALS) else "부분" if passed else "미확인"
                main = sig.get("yoy3m") if "yoy3m" in passed or not passed else sig[passed[0]]
                row["lag"] = main["best_lag"]          # 대표 시차(통과한 신호 우선)
                lags = [v["best_lag"] for v in sig.values() if v["best_lag"] is not None]
                row["lag_consistent"] = len(lags) == len(SIGNALS) and max(lags) - min(lags) <= 1   # 두 신호 시차가 1개월 안
            edges.append(row)
        _memo.clear()
        _memo[stamp] = {"thresholds": thresholds, "edges": edges}
        return _memo[stamp]
    finally:
        conn.close()
