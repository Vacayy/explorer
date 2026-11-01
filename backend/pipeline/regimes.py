"""국면 이력 (docs/specs/market-regimes.md, 근거 docs/research/market-regimes.md). LLM 0.

- 층 A 시장 국면: S&P500 일별 종가에 Lunde–Timmermann 대칭 20/20 규칙. 국면마다 확정일(규칙이 처음 충족된 날).
- 층 A 주석: 강세 안의 −10~20% 조정, −18% 이상은 임계 근접.
- 층 A′ 실시간 추세: 월말 종가 vs 10개월 단순이평(Faber).
- 층 B 경기 침체: FRED USREC.
- 버크셔 vs 지수: 누적 수익률·상대강도·롤링 12M 초과수익·36M 베타 조정·국면별 초과수익.
저장 테이블 없이 us_prices·market_indicators에서 매번 계산한다.
"""
import json
from datetime import date, datetime, timezone
from statistics import median

from database import get_connection

PARAMS = {"bear": 0.20, "bull": 0.20, "correction": 0.10, "near": 0.18, "trend_months": 10, "version": "lt-20-20/v1"}
INDEX = "^GSPC"
BRK_B, BRK_A = "BRK-B", "BRK-A"
BENCHES = {
    "sp500tr": {"ticker": "^SP500TR", "label": "S&P500 총수익", "dividends": True},
    "sp500": {"ticker": "^GSPC", "label": "S&P500", "dividends": False},
    "nasdaq": {"ticker": "^IXIC", "label": "나스닥 종합", "dividends": False},
}
TICKERS = (INDEX, "^SP500TR", "^IXIC", BRK_B, BRK_A)
RANGES = {"1y": 12, "3y": 36, "5y": 60, "10y": 120, "20y": 240, "all": None}   # 개월
FULL_HISTORY_ROWS = 1000   # 이보다 적으면 전 이력 백필
USREC_CACHE = "regimes:usrec"


# ── 읽기 ────────────────────────────────────────────────────────────────────

def _closes(conn, ticker: str) -> list[tuple[str, float]]:
    rows = conn.execute("SELECT trade_date, close FROM us_prices WHERE stock_code=? AND close > 0 ORDER BY trade_date",
                        (ticker,)).fetchall()
    return [(r[0], r[1]) for r in rows]


def _brk(conn) -> list[tuple[str, float]]:
    """BRK-B 단위 이력. BRK-B 상장(1996-05) 이전은 BRK-A를 첫 공통일 비율로 이어 붙인다."""
    b, a = _closes(conn, BRK_B), _closes(conn, BRK_A)
    if not b:
        return []
    a_map = dict(a)
    first = next((d for d, _ in b if d in a_map), None)
    if first is None:
        return b
    ratio = dict(b)[first] / a_map[first]
    return [(d, v * ratio) for d, v in a if d < b[0][0]] + b


def _recessions(conn) -> list[dict]:
    rows = conn.execute("SELECT snapshot_date, value FROM market_indicators WHERE indicator='regime_usrec' ORDER BY snapshot_date").fetchall()
    out, start, prev = [], None, None
    for d, v in rows:
        if v >= 1 and start is None:
            start = d
        if v < 1 and start is not None:
            out.append({"start": start, "end": _month_end(prev)})
            start = None
        prev = d
    if start is not None:
        out.append({"start": start, "end": _month_end(prev), "open": True})
    return out


def _month_end(d: str) -> str:
    y, m = int(d[:4]), int(d[5:7])
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1).isoformat()


# ── 층 A: Lunde–Timmermann ──────────────────────────────────────────────────

def turning_points(closes: list[float], bear: float = PARAMS["bear"], bull: float = PARAMS["bull"]) -> list[tuple[str, int, int]]:
    """[(kind 'peak'|'trough', 극점 인덱스, 확정 인덱스)]. 시작 상태는 먼저 충족된 쪽으로 정한다."""
    if not closes:
        return []
    state, hi, lo, turns = None, 0, 0, []
    for i in range(1, len(closes)):
        c = closes[i]
        if state != "bear" and c > closes[hi]:
            hi = i
        if state != "bull" and c < closes[lo]:
            lo = i
        if state != "bear" and c <= closes[hi] * (1 - bear):
            turns.append(("peak", hi, i))
            state = "bear"
            lo = min(range(hi, i + 1), key=closes.__getitem__)
        elif state != "bull" and c >= closes[lo] * (1 + bull):
            turns.append(("trough", lo, i))
            state = "bull"
            hi = max(range(lo, i + 1), key=closes.__getitem__)
    return turns


def phases_of(series: list[tuple[str, float]]) -> list[dict]:
    """극점 사이를 국면으로. 강세 = 저점→고점, 약세 = 고점→저점. 첫 극점 이전은 버리고, 마지막 전환 이후는 잠정."""
    if len(series) < 2:
        return []
    dates, closes = [d for d, _ in series], [v for _, v in series]
    turns = turning_points(closes)
    bounds = [(0, None)] + [(idx, conf) for _, idx, conf in turns] + [(len(closes) - 1, None)]
    kinds = ["bull" if (turns[0][0] if turns else "peak") == "peak" else "bear"]
    for kind, _, _ in turns:
        kinds.append("bear" if kind == "peak" else "bull")
    out = []
    for k, ((s, conf), (e, _)) in enumerate(zip(bounds, bounds[1:])):
        if e <= s or k == 0:   # 데이터 시작~첫 전환점은 상태를 모른다(첫 극점이 아직 확정 전)
            continue
        provisional = k == len(bounds) - 2
        out.append({"kind": kinds[k], "start": dates[s], "end": dates[e], "start_close": closes[s], "end_close": closes[e],
                    "change_pct": round((closes[e] / closes[s] - 1) * 100, 2),
                    "days": (date.fromisoformat(dates[e]) - date.fromisoformat(dates[s])).days,
                    "confirm_date": dates[conf] if conf is not None else None,
                    "confirm_lag_days": (date.fromisoformat(dates[conf]) - date.fromisoformat(dates[s])).days if conf is not None else None,
                    "provisional": provisional})
    return out


def corrections_of(series: list[tuple[str, float]], phases: list[dict]) -> list[dict]:
    """강세 국면 안에서 직전 최고 종가 대비 −10% 이상 내려간 구간(약세 문턱 미만). 끝 = 고점 회복일, 미회복이면 열림."""
    idx = {d: i for i, (d, _) in enumerate(series)}
    out = []
    for p in phases:
        if p["kind"] != "bull":
            continue
        s, e = idx[p["start"]], idx[p["end"]]
        top, low, open_ = s, None, False
        for i in range(s, e + 1):
            c = series[i][1]
            if c >= series[top][1]:
                if open_:
                    out.append(_correction(series, top, low, i))
                    open_ = False
                top, low = i, None
                continue
            if low is None or c < series[low][1]:
                low = i
            if not open_ and c <= series[top][1] * (1 - PARAMS["correction"]):
                open_ = True
        if open_:
            out.append(_correction(series, top, low, None))
    return out


def _correction(series, top, low, end) -> dict:
    dd = (series[low][1] / series[top][1] - 1) * 100
    return {"start": series[top][0], "trough": series[low][0], "end": series[end][0] if end is not None else None,
            "drawdown_pct": round(dd, 2), "near_threshold": dd <= -PARAMS["near"] * 100}


# ── 층 A′: 10개월선 ─────────────────────────────────────────────────────────

def _month_ends(series: list[tuple[str, float]]) -> list[tuple[str, float]]:
    out: dict[str, tuple[str, float]] = {}
    for d, v in series:
        out[d[:7]] = (d, v)
    return list(out.values())


def trend_of(series: list[tuple[str, float]]) -> list[dict]:
    """월말 종가 > 10개월 단순이평이면 up. 같은 상태의 연속 월을 한 구간으로(시작 = 그 신호가 난 월말)."""
    m, n = _month_ends(series), PARAMS["trend_months"]
    out: list[dict] = []
    for i in range(n - 1, len(m)):
        sma = sum(v for _, v in m[i - n + 1:i + 1]) / n
        state = "up" if m[i][1] > sma else "down"
        if out and out[-1]["state"] == state:
            out[-1]["end"] = m[i][0]
        else:
            out.append({"state": state, "start": m[i][0], "end": m[i][0]})
    for a, b in zip(out, out[1:]):   # 신호는 다음 신호 전까지 유효 — 구간이 끊기지 않게
        a["end"] = b["start"]
    if out:
        out[-1]["end"] = series[-1][0]
    return out


def _weekly(series: list[tuple[str, float]]) -> list[tuple[str, float]]:
    out: dict[tuple[int, int], tuple[str, float]] = {}
    for d, v in series:
        out[date.fromisoformat(d).isocalendar()[:2]] = (d, v)
    return list(out.values())


# ── 조회 ────────────────────────────────────────────────────────────────────

def get_regimes() -> dict:
    conn = get_connection()
    try:
        series = _closes(conn, INDEX)
        recessions = _recessions(conn)
        fetched = conn.execute("SELECT max(fetched_at) FROM us_prices WHERE stock_code=?", (INDEX,)).fetchone()[0]
    finally:
        conn.close()
    phases = phases_of(series)
    trend = trend_of(series)
    current = None
    if phases:
        last = phases[-1]
        seg = [v for d, v in series if d >= last["start"]]
        current = {"kind": last["kind"], "start": last["start"], "close": series[-1][1],
                   "from_peak_pct": round((series[-1][1] / max(seg) - 1) * 100, 2),
                   "from_trough_pct": round((series[-1][1] / min(seg) - 1) * 100, 2),
                   "trend": trend[-1]["state"] if trend else None}
    return {"as_of": series[-1][0] if series else None, "first_date": series[0][0] if series else None,
            "fetched_at": _iso(fetched), "params": PARAMS, "index": {"ticker": INDEX, "label": "S&P500"},
            "phases": phases, "corrections": corrections_of(series, phases), "trend": trend,
            "recessions": recessions, "series": _weekly(series), "current": current}


def _iso(stamp: str | None) -> str | None:
    return stamp.replace(" ", "T") + "Z" if stamp else None


def _months_before(d: str, months: int) -> str:
    y, m = divmod(int(d[:4]) * 12 + int(d[5:7]) - 1 - months, 12)
    return f"{y:04d}-{m + 1:02d}-{d[8:10]}"


def _at(series: list[tuple[str, float]], day: str) -> float | None:
    """day 이전(포함) 마지막 값."""
    lo, hi = 0, len(series)
    while lo < hi:
        mid = (lo + hi) // 2
        if series[mid][0] <= day:
            lo = mid + 1
        else:
            hi = mid
    return series[lo - 1][1] if lo else None


def _beta(br: list[float], ir: list[float]) -> float | None:
    n = len(ir)
    if n < 2:
        return None
    mb, mi = sum(br) / n, sum(ir) / n
    var = sum((x - mi) ** 2 for x in ir)
    return sum((b - mb) * (x - mi) for b, x in zip(br, ir)) / var if var else None


def get_brk(bench: str = "sp500tr", span: str = "all") -> dict:
    meta = BENCHES[bench]
    conn = get_connection()
    try:
        brk, idx, spx = _brk(conn), _closes(conn, meta["ticker"]), _closes(conn, INDEX)
        recessions = _recessions(conn)
    finally:
        conn.close()
    bench_map = dict(idx)
    common = [(d, v, bench_map[d]) for d, v in brk if d in bench_map]
    base = {"bench": {"key": bench, **meta, "first_date": idx[0][0] if idx else None},
            "brk_first_date": brk[0][0] if brk else None, "range": span}
    if len(common) < 2:
        return {**base, "as_of": None, "start": None, "points": [], "rolling": [], "phases": [], "summary": {}, "bands": []}
    as_of = common[-1][0]
    months = RANGES[span]
    start = max(common[0][0], _months_before(as_of, months)) if months else common[0][0]
    window = [c for c in common if c[0] >= start]
    d0, b0, i0 = window[0]
    pts = [{"date": d, "brk_pct": round((b / b0 - 1) * 100, 2), "bench_pct": round((i / i0 - 1) * 100, 2),
            "rs": round(b / i / (b0 / i0) * 100, 2)} for d, b, i in window]
    if months is None or months > 60:
        keep = {d for d, _ in _weekly([(p["date"], 0.0) for p in pts])}
        pts = [p for p in pts if p["date"] in keep]

    # 월말 롤링: 12M 초과수익, 36M 베타(월간 수익률 회귀), 베타 조정 초과
    me = _month_ends([(d, (b, i)) for d, b, i in common])
    rolling, betas = [], {}
    for k in range(1, len(me)):
        if k >= 36:
            br = [me[j][1][0] / me[j - 1][1][0] - 1 for j in range(k - 35, k + 1)]
            ir = [me[j][1][1] / me[j - 1][1][1] - 1 for j in range(k - 35, k + 1)]
            betas[me[k][0]] = _beta(br, ir)
        if k >= 12:
            b12 = me[k][1][0] / me[k - 12][1][0] - 1
            i12 = me[k][1][1] / me[k - 12][1][1] - 1
            beta = betas.get(me[k][0])
            rolling.append({"date": me[k][0], "brk_12m": round(b12 * 100, 2), "bench_12m": round(i12 * 100, 2),
                            "excess_12m": round((b12 - i12) * 100, 2), "beta_36m": round(beta, 3) if beta is not None else None,
                            "beta_adj_12m": round((b12 - beta * i12) * 100, 2) if beta is not None else None})
    beta_dates = sorted(betas)

    # 국면별(S&P500 국면) — 데이터 시작 전에 시작한 국면은 시작일을 잘라 싣고 clipped로 표시
    brk_s, bench_s = [(d, b) for d, b, _ in common], [(d, i) for d, _, i in common]
    phase_rows = []
    for p in phases_of(spx):
        if p["end"] <= common[0][0]:
            continue
        clipped = p["start"] < common[0][0]
        s = common[0][0] if clipped else p["start"]
        b_ret = _at(brk_s, p["end"]) / _at(brk_s, s) - 1
        i_ret = _at(bench_s, p["end"]) / _at(bench_s, s) - 1
        known = [d for d in beta_dates if d <= s]
        beta = betas[known[-1]] if known else None
        phase_rows.append({"kind": p["kind"], "start": p["start"], "end": p["end"], "provisional": p["provisional"],
                           "clipped_start": s if clipped else None,
                           "spx_change_pct": p["change_pct"], "confirm_date": p["confirm_date"], "confirm_lag_days": p["confirm_lag_days"],
                           "brk_pct": round(b_ret * 100, 2), "bench_pct": round(i_ret * 100, 2),
                           "excess_pct": round((b_ret - i_ret) * 100, 2), "beta": round(beta, 3) if beta is not None else None,
                           "beta_adj_pct": round((b_ret - beta * i_ret) * 100, 2) if beta is not None else None})
    summary = {}
    for kind in ("bull", "bear"):
        done = [r for r in phase_rows if r["kind"] == kind and not r["provisional"] and not r["clipped_start"]]
        summary[kind] = {"n": len(done), "brk_wins": sum(r["excess_pct"] > 0 for r in done),
                         "median_excess_pct": round(median(r["excess_pct"] for r in done), 2) if done else None,
                         "beta_adj_wins": sum((r["beta_adj_pct"] or 0) > 0 for r in done if r["beta_adj_pct"] is not None),
                         "beta_adj_n": sum(r["beta_adj_pct"] is not None for r in done)}

    bands = [{"kind": "bear", "start": max(p["start"], start), "end": p["end"], "provisional": p["provisional"]}
             for p in phase_rows if p["kind"] == "bear" and p["end"] >= start]
    bands += [{"kind": "recession", "start": max(r["start"], start), "end": min(r["end"], as_of), "provisional": bool(r.get("open"))}
              for r in recessions if r["end"] >= start and r["start"] <= as_of]
    return {**base, "as_of": as_of, "start": d0, "points": pts,
            "rolling": [r for r in rolling if r["date"] >= start], "phases": phase_rows, "summary": summary, "bands": bands}


# ── 수집 ────────────────────────────────────────────────────────────────────

def collect(force: bool = False) -> dict:
    """시세 5종 + USREC. 행이 적으면 전 이력, 아니면 최근 1개월. 실패는 소스별로 보고(조용히 0으로 넘기지 않는다)."""
    from pipeline.us_data import _prices_fresh, collect_prices
    results = []
    for t in TICKERS:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT COUNT(*) FROM us_prices WHERE stock_code=?", (t,)).fetchone()[0]
            fresh = _prices_fresh(conn, t)
        finally:
            conn.close()
        period = "max" if rows < FULL_HISTORY_ROWS else "1mo"
        if fresh and not force and period != "max":
            results.append({"key": t, "status": "skip", "rows": 0})
            continue
        try:
            got = collect_prices(t, period)
            results.append({"key": t, "status": "ok", "rows": got["collected_rows"], "period": period})
        except Exception as exc:  # noqa: BLE001 — 소스별 보고
            results.append({"key": t, "status": "error", "rows": 0, "error": str(exc)[:200]})
    results.append(_collect_usrec(force))
    from pipeline.era import collect_era   # 지금 시장 읽기용 FRED·Yahoo 계열(market_indicators.era_*)
    results += [{k: v for k, v in r.items() if k in ("key", "status", "rows", "error")} for r in collect_era(force)]
    return {"results": results, "collected_at": datetime.now(timezone.utc).isoformat()}


def _collect_usrec(force: bool) -> dict:
    from services.cache_service import is_cached, set_cache
    from pipeline.macro import _public_fred_history
    if is_cached(USREC_CACHE) and not force:
        return {"key": "USREC", "status": "skip", "rows": 0}
    try:
        rows = _public_fred_history("USREC", (date.today() - date(1900, 1, 1)).days)
    except Exception as exc:  # noqa: BLE001
        return {"key": "USREC", "status": "error", "rows": 0, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    if not rows:
        return {"key": "USREC", "status": "error", "rows": 0, "error": "FRED 응답이 비었습니다"}
    extra = json.dumps({"source": "FRED USREC", "fetched_at": datetime.now(timezone.utc).isoformat()})
    conn = get_connection()
    try:
        conn.executemany("INSERT INTO market_indicators (snapshot_date, indicator, value, extra_json, fetched_at) "
                         "VALUES (?, 'regime_usrec', ?, ?, datetime('now')) ON CONFLICT(snapshot_date, indicator) DO UPDATE SET "
                         "value=excluded.value, extra_json=excluded.extra_json, fetched_at=excluded.fetched_at",
                         [(d, v, extra) for d, v in rows])
        conn.commit()
    finally:
        conn.close()
    set_cache(USREC_CACHE, 7 * 86400)
    return {"key": "USREC", "status": "ok", "rows": len(rows)}
