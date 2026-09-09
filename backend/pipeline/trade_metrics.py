"""수출입 파생지표 + 급등·급감 판정 — data-watcher(별도 프로젝트)의 metrics.py를 이식 (D-140).

물질화하지 않고 요청 시 계산한다 — 관세청이 매월 전월까지를 정정하므로 저장된 파생값은 조용히 낡는다.
원본(trade_stats)만 진실로 둔다.

지표 정의:
  mom   전월 대비                          v[t] / v[t-1]  - 1
  yoy   전년 동월 대비                      v[t] / v[t-12] - 1
  qoq   **직전 3개월 합 대비 그 앞 3개월 합**  sum(t-2..t) / sum(t-5..t-3) - 1  (캘린더 분기 아님)
  yoy3m 3개월 합의 전년 동기 대비            sum(t-2..t) / sum(t-14..t-12) - 1  (계절성 잡음 완화)
  z_*   해당 품목 **그 지표 자신의 과거 분포** 기준 로버스트 z = (x - median) / (1.4826·MAD)
        관측 < 8 또는 MAD = 0 → None. YoY의 z를 MoM 판정에 쓰지 않는다(분산이 다르다).
판정:
  규모 게이트 value ≥ min_usd(기본 $10M) → mode=zscore |z| ≥ 2.0 / mode=fixed |metric| ≥ 임계
  flag = surge | plunge | new(기준월이 격자 안인데 값 0/없음 = 진짜 신규·재개) | none('이력 부족' 포함)
  contribution = |Δ| / Σ|Δ| (전년 동월 대비 증감액 기여도) — 하이라이트 기본 정렬 (작은 품목의 큰 %가 큰 품목을 밀어내지 않게)
"""
from statistics import median

from database import get_connection

Z_SCALE = 1.4826
MIN_Z_HISTORY = 8
LOOKBACK = {"mom": 1, "yoy": 12, "qoq": 6, "yoy3m": 15}
DEFAULTS = {
    "mode": "zscore",
    "metric": "yoy",
    "z_threshold": 2.0,
    "fixed_threshold": {"mom": 0.20, "yoy": 0.30, "qoq": 0.20, "yoy3m": 0.30},
    "min_usd": 10_000_000,
}


def _ratio(cur, base):
    if cur is None or base is None or base == 0:
        return None
    return cur / base - 1


def _window(vals, i, start, end):
    lo, hi = i - start, i - end
    if lo < 0:
        return None
    chunk = vals[lo:hi + 1]
    return None if any(v is None for v in chunk) else sum(chunk)


def robust_z(history: list[float], x: float) -> float | None:
    if len(history) < MIN_Z_HISTORY:
        return None
    m = median(history)
    mad = median([abs(h - m) for h in history])
    if mad == 0:
        return None
    return (x - m) / (Z_SCALE * mad)


def _month_grid(first: str, last: str) -> list[str]:
    fy, fm = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    out, y, m = [], fy, fm
    while (y, m) <= (ly, lm):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def derive(rows: list[dict], flow: str = "export") -> list[dict]:
    """한 품목의 월별 원본 → 지표가 붙은 시계열. 연속 월 격자로 펴서 인덱스 산술(결측 구멍 보정)."""
    key = f"{flow}_usd"
    if not rows:
        return []
    by_period = {r["period"]: r.get(key) for r in rows}
    grid = _month_grid(min(by_period), max(by_period))
    vals = [by_period.get(p) for p in grid]
    out = []
    history = {m: [] for m in LOOKBACK}
    for i, p in enumerate(grid):
        v = vals[i]
        m_vals = {
            "mom": _ratio(v, vals[i - 1] if i >= 1 else None),
            "yoy": _ratio(v, vals[i - 12] if i >= 12 else None),
            "qoq": _ratio(_window(vals, i, 2, 0), _window(vals, i, 5, 3)),
            "yoy3m": _ratio(_window(vals, i, 2, 0), _window(vals, i, 14, 12)),
        }
        zs = {}
        for m, x in m_vals.items():
            zs[f"z_{m}"] = robust_z(history[m], x) if x is not None else None
            if x is not None:
                history[m].append(x)
        out.append({"period": p, "idx": i, "value": v, **m_vals, **zs, "z": zs["z_yoy"]})
    return out


def classify(point: dict, *, mode: str, metric: str, z_threshold: float, fixed_threshold: dict, min_usd: float) -> dict:
    v = point.get("value")
    if v is None or v < min_usd:
        return {"flag": "none", "intensity": 0.0, "reason": "규모 게이트 미달"}
    x = point.get(metric)
    if x is None:
        need = LOOKBACK.get(metric, 12)
        idx = point.get("idx")
        if idx is not None and idx < need:
            return {"flag": "none", "intensity": 0.0, "reason": f"이력 부족({metric}에는 {need}개월 소급 필요)"}
        return {"flag": "new", "intensity": float(v), "reason": f"{metric} 기준값 없음(신규·재개)"}
    if mode == "zscore":
        z = point.get(f"z_{metric}", point.get("z"))
        if z is None:
            return {"flag": "none", "intensity": 0.0, "reason": "z 산출 불가(관측 부족 또는 MAD 0)"}
        if abs(z) < z_threshold:
            return {"flag": "none", "intensity": abs(z), "reason": f"z {z:+.1f}"}
        return {"flag": "surge" if z > 0 else "plunge", "intensity": abs(z), "reason": f"z {z:+.1f} ({metric} {x:+.1%})"}
    thr = fixed_threshold.get(metric, 0.30)
    if abs(x) < thr:
        return {"flag": "none", "intensity": abs(x), "reason": f"{metric} {x:+.1%}"}
    return {"flag": "surge" if x > 0 else "plunge", "intensity": abs(x), "reason": f"{metric} {x:+.1%} (임계 {thr:.0%})"}


def classify_all(point: dict, *, mode: str, z_threshold: float, fixed_threshold: dict, min_usd: float) -> dict:
    return {m: classify(point, mode=mode, metric=m, z_threshold=z_threshold, fixed_threshold=fixed_threshold, min_usd=min_usd)
            for m in LOOKBACK}


def add_contribution(rows: list[dict]) -> list[dict]:
    total = sum(abs(r.get("delta_usd") or 0) for r in rows)
    for r in rows:
        d = r.get("delta_usd") or 0
        r["contribution"] = (abs(d) / total) if total else None
    return rows


# ── explorer 테이블 위의 조회 계층 ─────────────────────────────────────────────

def _opts(**opt) -> dict:
    d = dict(DEFAULTS)
    for k, v in opt.items():
        if v is not None and k in d:
            d[k] = v
    return d


def raw_series(conn, hs_code: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT period, export_usd, import_usd, export_wt, import_wt FROM trade_stats WHERE hs_code=? ORDER BY period", (hs_code,))]


def periods(conn) -> list[str]:
    return [r["period"] for r in conn.execute("SELECT DISTINCT period FROM trade_stats ORDER BY period DESC")]


def item_series(hs_code: str) -> dict:
    """품목 상세 — 수출·수입 각각 파생지표 + 무역수지."""
    conn = get_connection()
    try:
        raw = raw_series(conn, hs_code)
        meta = conn.execute("SELECT hs_code, item_name, group_label FROM trade_follow WHERE hs_code=?", (hs_code,)).fetchone()
    finally:
        conn.close()
    exp, imp = derive(raw, "export"), derive(raw, "import")
    imp_by = {p["period"]: p for p in imp}
    keys = ("value", "mom", "yoy", "qoq", "yoy3m", "z")
    series = []
    for e in exp:
        i = imp_by.get(e["period"], {})
        ev, iv = e.get("value"), i.get("value")
        series.append({"period": e["period"], "export": {k: e.get(k) for k in keys}, "import": {k: i.get(k) for k in keys},
                       "balance": (ev - iv) if (ev is not None and iv is not None) else None})
    return {"item": dict(meta) if meta else {"hs_code": hs_code, "item_name": hs_code, "group_label": None}, "series": series}


def table(period: str | None = None, flow: str = "export", **opt) -> dict:
    """팔로우 전 품목 × 선택 시점(기본 최신월) 지표 + 판정 + 그룹 집계. 하이라이트와 같은 판정을 쓴다."""
    o = _opts(**opt)
    conn = get_connection()
    try:
        all_periods = periods(conn)
        if not all_periods:
            return {"period": None, "periods": [], "flow": flow, "options": o, "rows": [], "groups": [], "empty": True}
        period = period or all_periods[0]
        items = [dict(r) for r in conn.execute(
            "SELECT hs_code, item_name, group_label FROM trade_follow WHERE active=1 ORDER BY group_label, hs_code")]
        rows = []
        for it in items:
            derived = derive(raw_series(conn, it["hs_code"]), flow)
            point = next((d for d in derived if d["period"] == period), None)
            if point is None:
                rows.append({**it, "value": None, "flag": "none", "intensity": 0.0, "reason": "기준월 데이터 없음", "missing": True,
                             "grid": {m: {"flag": "none", "reason": "기준월 데이터 없음"} for m in LOOKBACK}})
                continue
            idx = derived.index(point)
            prev_year = derived[idx - 12]["value"] if idx >= 12 else None
            v = point["value"]
            verdict = classify(point, mode=o["mode"], metric=o["metric"], z_threshold=o["z_threshold"],
                               fixed_threshold=o["fixed_threshold"], min_usd=o["min_usd"])
            grid = classify_all(point, mode=o["mode"], z_threshold=o["z_threshold"], fixed_threshold=o["fixed_threshold"], min_usd=o["min_usd"])
            rows.append({**it, "value": v, "mom": point["mom"], "yoy": point["yoy"], "qoq": point["qoq"], "yoy3m": point["yoy3m"],
                         "z": point["z"], "z_mom": point["z_mom"], "z_yoy": point["z_yoy"], "z_qoq": point["z_qoq"], "z_yoy3m": point["z_yoy3m"],
                         "grid": {m: {"flag": g["flag"], "reason": g["reason"]} for m, g in grid.items()},
                         "delta_usd": (v - prev_year) if (v is not None and prev_year is not None) else None, **verdict})
    finally:
        conn.close()
    add_contribution(rows)
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r["group_label"] or "미분류", {"group_label": r["group_label"] or "미분류", "count": 0, "value": 0.0, "surge": 0, "plunge": 0})
        g["count"] += 1
        g["value"] += r.get("value") or 0
        if r["flag"] == "surge":
            g["surge"] += 1
        elif r["flag"] == "plunge":
            g["plunge"] += 1
    return {"period": period, "periods": all_periods, "flow": flow, "options": o, "rows": rows,
            "groups": sorted(groups.values(), key=lambda g: -g["value"])}


def highlights(period: str | None = None, flow: str = "export", limit: int = 8, rank: str = "contribution", **opt) -> dict:
    """급등·급감 랭킹 — 기본은 기여도 순(무엇이 전체를 움직였나), rank=intensity면 이례성 순."""
    t = table(period, flow, **opt)
    flagged = [r for r in t["rows"] if r.get("flag") in ("surge", "plunge", "new")]
    if rank == "intensity":
        flagged.sort(key=lambda r: -(r.get("intensity") or 0))
    else:
        flagged.sort(key=lambda r: (-(r.get("contribution") or 0), -(r.get("intensity") or 0)))
    return {"period": t["period"], "periods": t.get("periods", []), "flow": flow, "options": {**t["options"], "rank": rank},
            "total_usd": sum(r.get("value") or 0 for r in t["rows"]),
            "surge": [r for r in flagged if r["flag"] in ("surge", "new")][:limit],
            "plunge": [r for r in flagged if r["flag"] == "plunge"][:limit], "groups": t["groups"]}
