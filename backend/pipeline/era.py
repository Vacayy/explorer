"""지금 시장 읽기 — 네 층 (docs/specs/market-regimes.md §8, 근거 docs/research/era-methodology.md). 판정은 LLM 0.

층 1 상태: 두 단계 — 경계(월말 종가 < 12개월선)·확정(252일 신저가 이탈 또는 200일선 하락). 1956년 이후 통계와 과거 에피소드의 이후 경로를 매번 다시 잰다.
층 2 의미 국면: 주식–금리 상관의 부호(월간 36개월). 음(−)=인플레이션형(금리 급등·인상이 위험), 양(+)=디스인플레이션형(급락·인하가 위험).
층 3 온도: Howard Marks 체크리스트 중 무료 데이터로 판정 가능한 정량 항목 + 사람이 체크하는 정성 항목(era_checks).
층 4 전제 원장: 구루 전제마다 반증 지표와 판정 규칙. 시점 없는 전제는 '반증 불가'.
"""
import json
from datetime import date, datetime, timezone

import numpy as np

from database import get_connection
from pipeline.regimes import INDEX, _closes, _month_ends, corrections_of, phases_of

# ── 수집 계열(FRED 공개 CSV, 키 불필요) — market_indicators.era_* ──
ERA_SERIES = {
    "dgs30": ("DGS30", "미 30년 금리", "%"),
    "dfii10": ("DFII10", "10년 실질금리(TIPS)", "%"),
    "t5yifr": ("T5YIFR", "5년 뒤 5년 기대인플레", "%"),
    "tp10": ("THREEFYTP10", "10년 기간 프리미엄(ACM)", "%"),
    "t10y3m": ("T10Y3M", "10Y − 3M 금리차", "%p"),
    "dtb3": ("DTB3", "미 3개월 국채", "%"),
    "dff": ("DFF", "연방기금금리", "%"),
    "cpi": ("CPIAUCSL", "CPI 지수(월)", "지수"),
    "hy_ey": ("BAMLH0A0HYM2EY", "하이일드 실효수익률", "%"),
}
ERA_YAHOO = {"gold": ("GC=F", "금 선물", "$"), "dxy": ("DX-Y.NYB", "달러지수", "지수")}   # Yahoo 무키 — 12개월 변화용
ERA_CACHE = "era:collect"
CHECK_KEYS = {   # Marks 체크리스트의 심리·행동 항목 — 사람이 hot/neutral/cold로 기록
    "no_price_too_high": "'가격은 상관없다', '이번엔 다르다'는 말이 흔한가",
    "bull_stage": "강세장 3단계 중 '모두가 영원히 좋아질 거라 믿는' 단계인가",
    "outsiders": "금융과 무관한 사람들이 투자 얘기를 하는가",
    "deal_quality": "약한 약정·적자 기업 IPO·첫날 2배 같은 딜이 통하는가",
    "leverage_structure": "순환 거래·장부 밖 부채·만기 불일치 구조가 늘고 있는가",
    "fraud_cluster": "사기·부실이 연달아 드러나는가(호황 말기 신호)",
    "goldilocks": "물가 안정·침체 없음·금리 인하가 모두 가격에 반영됐는가",
    "private_credit": "사모 신용 스트레스(BDC 환매 제한·NAV 할인·PIK 증가)가 보이는가",
}
# 실험 결과(docs/research/regime-signals.md, 2026-10-26) — 화면에 출처와 함께 싣는 고정 통계
RESEARCH = {
    "conditional_rates": {"a": "1956–89: 켜졌을 때 12개월 안 −20% 낙폭 19% vs 꺼졌을 때 9%",
                          "b": "1990–2025: 24% vs 12%", "note": "결과를 본 뒤 세운 규칙 — 가설"},
}


def _series(conn, indicator: str) -> list[tuple[str, float]]:
    return [(r[0], r[1]) for r in conn.execute(
        "SELECT snapshot_date, value FROM market_indicators WHERE indicator=? AND value IS NOT NULL ORDER BY snapshot_date", (indicator,))]


def _last(s):
    return s[-1] if s else (None, None)


def _at(s: list[tuple[str, float]], day: str):
    import bisect
    k = bisect.bisect_right([d for d, _ in s], day)
    return s[k - 1][1] if k else None


def _months_before(d: str, n: int) -> str:
    y, m = divmod(int(d[:4]) * 12 + int(d[5:7]) - 1 - n, 12)
    return f"{y:04d}-{m + 1:02d}-{min(int(d[8:10]), 28):02d}"


def _yoy(monthly: list[tuple[str, float]]) -> list[tuple[str, float]]:
    m = {d[:7]: v for d, v in monthly}
    return [(d, (v / m[f"{int(d[:4]) - 1}{d[4:7]}"] - 1) * 100) for d, v in monthly if f"{int(d[:4]) - 1}{d[4:7]}" in m]


# ── 층 1 ────────────────────────────────────────────────────────────────────
# 두 단계 판정(docs/research/regime-signals.md §07, 2026-10-27 실험): 이평 길이보다 '언제 확인하느냐'가 헛경보를 가른다.
#   경계 = 월말 종가 < 12개월 이동평균(월말에만 바뀜). 1956–89·1990–2026 모두 약세장 전부 포착, 헛경보 10년에 약 2번
#   확정 = 252일 신저가 이탈(이후 63일 유지) 또는 200일선 20일 기울기 < 0. 늦지만 헛경보가 거의 없다
HORIZON = 252          # 이후 추이를 볼 거래일
PATH_STEP = 5          # 경로 표본 간격(거래일)
NEW_LOW_HOLD = 63


def _signals(C: np.ndarray, dates: list[str]):
    """일별 경계·확정 신호(불리언 배열)와 보조값."""
    n = len(C)
    me = [i for i in range(n - 1) if dates[i][:7] != dates[i + 1][:7]]   # 완결된 월말
    warn = np.zeros(n, bool)
    sma12_at = {}
    for j in range(11, len(me)):
        i = me[j]
        sma = C[me[j - 11:j + 1]].mean()
        sma12_at[i] = sma
        end = me[j + 1] if j + 1 < len(me) else n
        warn[i:end] = C[i] < sma        # 월말 판정을 다음 월말까지 유지
    # 252일 신저가(그날 이전 252일 최저 종가 아래) → 63일 유지
    low_prev = np.full(n, np.inf)
    win = np.lib.stride_tricks.sliding_window_view(C, 252).min(axis=1)   # win[k] = C[k:k+252].min()
    low_prev[252:] = win[:n - 252]
    brk = C < low_prev
    last = np.full(n, -10**9)
    cur = -10**9
    for i in range(n):
        if brk[i]: cur = i
        last[i] = cur
    new_low = (np.arange(n) - last) <= NEW_LOW_HOLD
    cs = np.cumsum(np.r_[0, C])
    m200 = np.full(n, np.nan)
    m200[199:] = (cs[200:] - cs[:-200]) / 200
    slope_down = np.zeros(n, bool)
    slope_down[220:] = m200[220:] < m200[200:-20]
    confirm = new_low | slope_down
    return warn, confirm, new_low, slope_down, m200, me, sma12_at, last


def _episodes(sig, C, dates, inbear, deep, rebound, lo):
    """꺼짐→켜짐 전환마다: 날짜·결과(bear|rebound|correction|false)·켜질 때 고점 대비·이후 경로(켜진 날 = 100).
    rebound = 약세장이 끝난 뒤 6개월 안(52주 고점이 아직 약세 전 고점이라 낙폭 신호가 남는 구간)."""
    n = len(C)
    out = []
    for i in range(max(lo, 1), n):
        if not (sig[i] and not sig[i - 1]):
            continue
        hi52 = C[max(0, i - 252):i + 1].max()
        end = min(n - 1, i + HORIZON)
        path = [[k, round(float(C[i + k] / C[i] * 100), 2)] for k in range(0, end - i + 1, PATH_STEP)]
        fut = C[i:end + 1]
        out.append({"date": dates[i], "outcome": "bear" if inbear[i] else "rebound" if rebound[i] else "correction" if deep[i] else "false",
                    "drawdown_at": round(float(C[i] / hi52 - 1) * 100, 1),
                    "min_after": round(float(fut.min() / C[i] - 1) * 100, 1),
                    "ret_after": round(float(C[end] / C[i] - 1) * 100, 1) if end - i >= HORIZON else None,
                    "complete": end - i >= HORIZON, "path": path})
    return out


def _median_path(eps):
    done = [e["path"] for e in eps if e["complete"]]
    if not done:
        return []
    L = min(len(p) for p in done)
    return [[done[0][k][0], round(float(np.median([p[k][1] for p in done])), 2)] for k in range(L)]


def _stats(sig, C, dates, bears, inbear, deep, lo):
    n = len(C)
    yrs = (n - lo) / 252
    B = [(a, b) for a, b in bears if a >= lo]
    already, remain, caught = [], [], 0
    for a, b in B:
        hit = next((i for i in range(a + 1, b + 1) if sig[i]), None)
        if hit is None:
            continue
        caught += 1
        already.append(C[hit] / C[a] - 1)
        remain.append(C[b] / C[hit] - 1)
    on = [i for i in range(max(lo, 1), n) if sig[i] and not sig[i - 1]]
    false = sum(1 for i in on if not inbear[i] and not deep[i])
    return {"bears_caught": caught, "bears_total": len(B),
            "drawdown_at_median": round(float(np.median(already)) * 100, 1) if already else None,
            "remaining_median": round(float(np.median(remain)) * 100, 1) if remain else None,
            "false_per_decade": round(false / yrs * 10, 1), "episodes": len(on), "false": false}


def layer_state(conn) -> dict:
    s = _closes(conn, INDEX)
    if len(s) < 600:
        return {"available": False}
    dates, C = [d for d, _ in s], np.array([v for _, v in s])
    n = len(C)
    warn, confirm, new_low, slope_down, m200, me, sma12_at, last_low = _signals(C, dates)
    ph = phases_of(s)
    co = corrections_of(s, ph)
    idx = {d: i for i, d in enumerate(dates)}
    bears = [(idx[p["start"]], idx[p["end"]]) for p in ph if p["kind"] == "bear" and not p["provisional"]]
    inbear = np.zeros(n, bool)
    for a, b in bears:
        inbear[a + 1:b + 1] = True
    deep = np.zeros(n, bool)
    for c in co:
        if c["drawdown_pct"] <= -15:
            deep[idx[c["start"]]:(idx[c["end"]] if c["end"] else n - 1) + 1] = True
    rebound = np.zeros(n, bool)
    for a, b in bears:
        rebound[b + 1:b + 127] = True
    lo = next(i for i, d in enumerate(dates) if d >= "1956-01")

    # 지금 — 경계는 마지막 완결 월말 판정 + 이번 달 잠정(완결 11개 월말 + 오늘)
    last_me = me[-1]
    sma_off = sma12_at[last_me]
    sma_now = float((C[me[-11:]].sum() + C[-1]) / 12)
    hi52 = C[max(0, n - 253):].max()
    year_ago = C[max(0, n - 1 - 252)]
    since = lambda sig: next((dates[i] for i in range(n - 1, 0, -1) if sig[i] != sig[i - 1]), None)
    stage = "confirm" if confirm[-1] else "warn" if warn[-1] else "none"

    def pack(sig, label, rule):
        eps = _episodes(sig, C, dates, inbear, deep, rebound, lo)
        return {"on": bool(sig[-1]), "since": since(sig), "label": label, "rule": rule, "stats": _stats(sig, C, dates, bears, inbear, deep, lo),
                "episodes": eps, "median_path": {k: _median_path([e for e in eps if e["outcome"] == k]) for k in ("bear", "rebound", "correction", "false")}}

    return {"available": True, "as_of": dates[-1], "close": float(C[-1]), "stage": stage,
            "warn": {**pack(warn, "경계 — 월말 종가가 12개월 이동평균 아래", "월말에만 판정. 다음 월말까지 유지"),
                     "month_end": dates[last_me], "vs_sma_pct": round(float(C[last_me] / sma_off - 1) * 100, 2),
                     "provisional_on": bool(C[-1] < sma_now), "provisional_vs_sma_pct": round(float(C[-1] / sma_now - 1) * 100, 2)},
            "confirm": {**pack(confirm, "확정 — 1년 신저가 이탈 또는 200일선이 꺾여 내려감", "둘 중 하나. 신저가 이탈은 이후 63거래일 유지"),
                        "new_low": bool(new_low[-1]), "last_new_low": dates[int(last_low[-1])] if last_low[-1] >= 0 else None,
                        "slope_down": bool(slope_down[-1]), "ma200_slope_pct": round(float(m200[-1] / m200[-21] - 1) * 100, 2)},
            "reference": {"ret_12m": round(float(C[-1] / year_ago - 1) * 100, 1), "from_52w_high": round(float(C[-1] / hi52 - 1) * 100, 1)},
            "current_path": [[k, round(float(C[i0 + k] / C[i0] * 100), 2)] for i0 in [next((i for i in range(n - 1, 0, -1) if not (warn | confirm)[i - 1] and (warn | confirm)[i]), n - 1)]
                             for k in range(0, n - i0, PATH_STEP)] if (warn | confirm)[-1] else [],
            "recession_hint": _recession_hint(conn, dates[-1])}


def _recession_hint(conn, as_of):
    t = _series(conn, "era_t10y3m")
    inverted = [v for d, v in t if d >= _months_before(as_of, 24)]
    return {"inverted_24m": (min(inverted) < 0) if inverted else None, "min_24m": round(min(inverted), 2) if inverted else None}


# ── 층 2 ────────────────────────────────────────────────────────────────────

def layer_meaning(conn) -> dict:
    spx = _closes(conn, INDEX)
    ten = _series(conn, "risk_us10y")
    if not spx or not ten:
        return {"available": False}
    s_me = {d[:7]: v for d, v in _month_ends(spx)}
    t_me = {d[:7]: v for d, v in _month_ends(ten)}
    months = sorted(set(s_me) & set(t_me))
    rets = [(b, s_me[b] / s_me[a] - 1, t_me[b] - t_me[a]) for a, b in zip(months, months[1:])]
    corr = []
    for k in range(35, len(rets)):
        w = rets[k - 35:k + 1]
        corr.append((rets[k][0] + "-28", round(float(np.corrcoef([x[1] for x in w], [x[2] for x in w])[0, 1]), 3)))
    # 일별 250일
    tmap = dict(ten)
    days = [d for d, _ in spx if d in tmap][-251:]
    sp = dict(spx)
    r = np.diff(np.log([sp[d] for d in days]))
    y = np.diff([tmap[d] for d in days])
    corr250 = round(float(np.corrcoef(r, y)[0, 1]), 3) if len(r) > 100 else None
    cpi = _yoy(_series(conn, "era_cpi"))
    c36 = corr[-1][1] if corr else None
    regime = None if c36 is None else ("inflation" if c36 < 0 else "disinflation")
    # 조건부 금리 신호 — 6개월 변화
    as_of = ten[-1][0]
    d10 = ten[-1][1] - (_at(ten, _months_before(as_of, 6)) or ten[-1][1])
    bill = _series(conn, "era_dtb3")
    d3 = (bill[-1][1] - _at(bill, _months_before(bill[-1][0], 6))) if bill and _at(bill, _months_before(bill[-1][0], 6)) is not None else None
    if regime == "inflation":
        flag = d10 > 0.75 or (d3 is not None and d3 > 1.0)
        rule = "인플레이션형 — 10년 금리 6개월 +0.75%p 초과 또는 3개월 금리 +1%p 초과면 경보"
    else:
        flag = d10 < -0.75 or (d3 is not None and d3 < -1.0)
        rule = "디스인플레이션형 — 10년 금리 6개월 −0.75%p 미만 또는 3개월 금리 −1%p 미만이면 경보"
    decades = {}
    for d, v in corr:
        decades.setdefault(d[:3] + "0s", []).append(v)
    return {"available": True, "as_of": corr[-1][0][:7] if corr else None, "corr_36m": c36, "corr_250d": corr250,
            "regime": regime, "cpi_yoy": round(cpi[-1][1], 2) if cpi else None, "cpi_month": cpi[-1][0][:7] if cpi else None,
            "rate_change_6m": {"us10y": round(d10, 2), "bill3m": round(d3, 2) if d3 is not None else None},
            "conditional_flag": bool(flag), "rule": rule, "research": RESEARCH["conditional_rates"],
            "decades": {k: round(float(np.mean(v)), 2) for k, v in decades.items()},
            "corr_series": corr}


# ── 층 3 ────────────────────────────────────────────────────────────────────

def _temp(key, label, value, unit, state, basis, source):
    return {"key": key, "label": label, "value": value, "unit": unit, "state": state, "basis": basis, "source": source}


def layer_temperature(conn) -> dict:
    items = []
    cpi = _yoy(_series(conn, "era_cpi"))
    dff = _series(conn, "era_dff")
    if cpi and dff:
        real = dff[-1][1] - cpi[-1][1]
        items.append(_temp("real_policy", "실질 정책금리(연방기금 − CPI)", round(real, 2), "%p",
                           "hot" if real < 0 else "cold" if real > 1 else "normal", "0 미만 = 강한 부양(뜨거움), +1 초과 = 긴축(차가움)", "FRED DFF·CPIAUCSL"))
    if cpi:
        v = cpi[-1][1]
        items.append(_temp("inflation", "CPI 전년비", round(v, 2), "%", "hot" if v <= 2.5 else "cold" if v >= 4 else "normal",
                           "2.5% 이하 = 잠잠(뜨거움 쪽 환경), 4% 이상 = 높음(차가움)", "FRED CPIAUCSL"))
    ten = _series(conn, "risk_us10y")
    if ten:
        v = ten[-1][1]
        items.append(_temp("rate_level", "10년 금리 수준", round(v, 2), "%", "hot" if v < 2 else "cold" if v >= 4 else "normal",
                           "2% 미만 = 사상 최저권(뜨거움), 4% 이상 = 정상 이상(차가움)", "FRED DGS10"))
    hy = _series(conn, "risk_hy")
    if hy:
        v = hy[-1][1] * 100
        items.append(_temp("hy_spread", "하이일드 스프레드(OAS)", round(v), "bp", "hot" if v < 400 else "cold" if v > 600 else "normal",
                           "정상 범위 400~600bp — 아래면 얇음(뜨거움), 위면 넓음(차가움)", "FRED BAMLH0A0HYM2"))
    ey = _series(conn, "era_hy_ey")
    if ey:
        v = ey[-1][1]
        items.append(_temp("hy_yield", "하이일드 실효수익률", round(v, 2), "%", "hot" if v < 6 else "cold" if v > 8 else "normal",
                           "기관 목표수익 6~7%와 비교 — 6% 미만 = 기대수익 부족(뜨거움)", "FRED BAMLH0A0HYM2EY"))
    vix = _series(conn, "risk_vix")
    if vix:
        v = vix[-1][1]
        items.append(_temp("vix", "VIX", round(v, 1), "", "hot" if v < 14 else "cold" if v > 25 else "normal",
                           "14 미만 = 위험회피 부재(뜨거움), 25 초과 = 공포(차가움)", "Yahoo ^VIX"))
    spx = _closes(conn, INDEX)
    if spx:
        ye = {d[:4]: v for d, v in spx}
        yrs = sorted(ye)
        full = [y for y in yrs if y < spx[-1][0][:4]]
        rets = {b: ye[b] / ye[a] - 1 for a, b in zip(full, full[1:])}
        last2 = [rets.get(full[-1]), rets.get(full[-2])] if len(full) > 2 else []
        both = len(last2) == 2 and all(r is not None and r >= 0.2 for r in last2)
        items.append(_temp("two_20", "직전 2년 연속 +20% 상승", f"{full[-2]} {last2[1] * 100:+.0f}% · {full[-1]} {last2[0] * 100:+.0f}%" if last2 else None, "",
                           "hot" if both else "normal", "2년 연속 +20%면 뜨거움(과거 5번 중 3번은 다음 2년 하락 — Marks)", "S&P500 연말 종가"))
        ph = [p for p in phases_of(spx) if p["kind"] == "bear" and not p["provisional"] and p["days"] >= 365]
        if ph:
            yrs_since = (date.fromisoformat(spx[-1][0]) - date.fromisoformat(ph[-1]["end"])).days / 365.25
            items.append(_temp("memory", "마지막 장기 약세장(1년 이상) 이후", round(yrs_since, 1), "년", "hot" if yrs_since > 10 else "normal",
                               f"마지막 장기 약세장 {ph[-1]['start'][:7]}~{ph[-1]['end'][:7]}. 10년 넘으면 기억이 짧아짐(뜨거움)", "S&P500 국면"))
    checks = {r["key"]: {"state": r["state"], "note": r["note"], "updated_at": r["updated_at"]}
              for r in conn.execute("SELECT key, state, note, updated_at FROM era_checks")}
    judged = [{"key": k, "label": label, **checks.get(k, {"state": None, "note": None, "updated_at": None})} for k, label in CHECK_KEYS.items()]
    states = [i["state"] for i in items] + [j["state"] for j in judged if j["state"]]
    hot, cold = states.count("hot"), states.count("cold")
    verdict = "hot" if hot - cold >= 3 else "cold" if cold - hot >= 3 else "balanced"
    return {"items": items, "judged": judged, "hot": hot, "cold": cold, "normal": states.count("normal"), "verdict": verdict,
            "missing": ["forward P/E", "상위 종목 집중도", "시가총액/GDP", "하이일드 부도율", "BDC 할인·PIK"]}


# ── 층 4 ────────────────────────────────────────────────────────────────────

def _memo(conn, slug):
    r = conn.execute("SELECT id, title, published_at FROM raw_documents WHERE source_type='memo' AND source_id=?", (f"oaktree/{slug}",)).fetchone()
    return {"doc_id": r["id"], "title": r["title"], "date": (r["published_at"] or "")[:10], "url": None} if r else None


def _ext(title, date_, url):
    return {"doc_id": None, "title": title, "date": date_, "url": url}


def _chg(s, months):
    if not s:
        return None
    old = _at(s, _months_before(s[-1][0], months))
    return None if old in (None, 0) else (s[-1][1] / old - 1) * 100


def layer_premises(conn, meaning: dict) -> list[dict]:
    v = lambda k: _last(_series(conn, k))[1]
    real, ten, t30, tp, be = v("era_dfii10"), v("risk_us10y"), v("era_dgs30"), v("era_tp10"), v("era_t5yifr")
    gold, dxy = _chg(_series(conn, "era_gold"), 12), _chg(_series(conn, "era_dxy"), 12)
    out = []

    def add(key, claim, who, kind, evidence, status, rule, sources):
        out.append({"key": key, "claim": claim, "who": who, "kind": kind, "evidence": evidence, "status": status, "rule": rule,
                    "sources": [s for s in sources if s]})

    st = None if real is None or ten is None else ("supports" if real > 1 and ten > 3 else "challenges" if real < 0.5 else "mixed")
    add("low_rate_over", "2009~21년 초저금리·저물가 시대는 끝났다", "Marks · BIS · Summers · El-Erian", "공유",
        [f"10년 실질금리 {real:.2f}%" if real is not None else None, f"10년 금리 {ten:.2f}%" if ten is not None else None],
        st, "실질금리 > 1% 이고 10년 > 3% 면 지지, 실질금리 < 0.5% 로 돌아가면 반증",
        [_memo(conn, "sea-change"), _memo(conn, "further-thoughts-on-sea-change"), _ext("BIS 연차보고서 2024", "2024-06", "https://www.bis.org/publ/arpdf/ar2024e1.htm")])
    c = meaning.get("corr_36m")
    add("stock_bond", "주식과 채권이 같이 움직이는 인플레이션형 국면이다", "AQR · Man Group · BIS · Bridgewater", "공유",
        [f"주식–금리 상관(36개월) {c:+.2f}" if c is not None else None, f"CPI 전년비 {meaning.get('cpi_yoy')}%" if meaning.get("cpi_yoy") is not None else None],
        None if c is None else ("supports" if c < 0 else "challenges"), "주식 수익률과 금리 변화의 상관이 음수면 지지(금리↑ = 주식↓)",
        [_ext("AQR, A Changing Stock-Bond Correlation", "2023-02", "https://www.aqr.com/Insights/Research/Journal-Article/A-Changing-Stock-Bond-Correlation"),
         _ext("BIS Quarterly Review", "2023-12", "https://bis.org/publ/qtrpdf/r_qt2312v.htm")])
    st = None if t30 is None or tp is None else ("supports" if t30 > 5 and tp > 0.5 else "challenges" if tp < 0 else "mixed")
    add("bond_discipline", "장기금리가 재정 적자를 규율한다(채권 자경단)", "Druckenmiller", "분기",
        [f"30년 금리 {t30:.2f}%" if t30 is not None else None, f"10년 기간 프리미엄 {tp:.2f}%" if tp is not None else None],
        st, "30년 > 5% 이고 기간 프리미엄 > 0.5% 면 지지, 프리미엄이 0 아래로 가면 반증",
        [_ext("Druckenmiller CNBC 대담", "2024-05", "https://www.cnbc.com/2024/05/07/cnbc-exclusive-cnbc-transcript-billionaire-investor-stanley-druckenmiller-speaks-with-cnbcs-squawk-box-today.html"),
         _ext("CBO 예산·경제 전망 2026~2036", "2026-02", "https://www.cbo.gov/publication/61882")])
    st = None if gold is None or be is None else ("supports" if gold > 15 and (dxy or 0) < 0 and be > 2.5 else "challenges" if gold < 0 and be < 2.2 else "mixed")
    add("debasement", "부채는 인플레이션과 통화가치 하락으로 해소된다", "Dalio · Paul Tudor Jones", "분기",
        [f"금 12개월 {gold:+.1f}%" if gold is not None else None, f"달러지수 12개월 {dxy:+.1f}%" if dxy is not None else None,
         f"5년 뒤 5년 기대인플레 {be:.2f}%" if be is not None else None],
        st, "금 +15% 초과·달러 약세·기대인플레 > 2.5% 가 함께면 지지. 다만 시점이 없어 최종 반증은 불가",
        [_ext("Dalio, How Countries Go Broke", "2025", "https://economicprinciples.org/how-countries-go-broke"),
         _ext("Fortune, Dalio Big Cycle 5단계", "2026-03", "https://fortune.com/2026/03/14/ray-dalio-big-cycle-debt-crisis-political-disorder-world-order/")])
    add("fiscal_chronic", "재정 부담은 위기 한 번보다 만성 고금리·달러 약세로 나타난다", "Marks", "분기",
        [f"10년 금리 {ten:.2f}%" if ten is not None else None, f"달러지수 12개월 {dxy:+.1f}%" if dxy is not None else None],
        "untestable", "시점이 없다('2년일지 20년일지') — 반증 불가로 표시하고 지표만 추적",
        [_memo(conn, "the-impact-of-debt"), _memo(conn, "shall-we-repeal-the-laws-of-economics---part-iii")])
    add("ai_bubble", "AI는 진짜 기술이지만 투자 쪽에는 거품이 따라온다", "Marks · Grantham(거품 쪽) · Sequoia Cahn(매출 격차)", "분기",
        ["필요 매출 격차 $1.5T(Cahn, 2026-07)"], "nodata", "상위 종목 집중도·설비투자 대비 AI 매출을 아직 수집하지 않는다",
        [_memo(conn, "ai-hurtles-ahead"), _memo(conn, "is-it-a-bubble"), _ext("GMO, Valuing AI", "2026-01", "https://www.gmo.com/americas/research-library/valuing-ai-extreme-bubble-new-golden-era-or-both_viewpoints/"),
         _ext("Cahn, AI's $1.5T Question", "2026-07", "https://dcahn.substack.com/p/ais-15t-question")])
    add("ai_rstar", "AI 투자는 중립금리를 올린다 — 금리를 낮춰 주지 않는다", "Fed Barr", "분기",
        [f"10년 실질금리 {real:.2f}%" if real is not None else None], None if real is None else ("supports" if real > 1.5 else "mixed"),
        "실질금리가 1.5% 위에 머물면 지지", [_ext("Barr 연설", "2026-02", "https://www.federalreserve.gov/newsevents/speech/barr20260217a.htm")])
    add("private_credit", "사모 신용(직접 대출)에 금이 가기 시작했다", "Marks", "Marks 고유", ["BDC 할인·환매 제한·PIK 미수집"], "nodata",
        "BDC NAV 할인·PIK 비중을 수집하면 판정", [_memo(conn, "whats-going-on-in-private-credit"), _memo(conn, "cockroaches-in-the-coal-mine")])
    for p in out:
        p["evidence"] = [e for e in p["evidence"] if e]
    return out


def get_state() -> dict:
    conn = get_connection()
    try:
        state = layer_state(conn)
        meaning = layer_meaning(conn)
        temp = layer_temperature(conn)
        premises = layer_premises(conn, meaning)
        memos = [{"doc_id": r["id"], "title": r["title"], "date": (r["published_at"] or "")[:10]} for r in conn.execute(
            "SELECT id, title, published_at FROM raw_documents WHERE source_type='memo' ORDER BY published_at DESC LIMIT 3")]
    finally:
        conn.close()
    return {"state": state, "meaning": meaning, "temperature": temp, "premises": premises, "latest_memos": memos,
            "generated_at": datetime.now(timezone.utc).isoformat()}


def set_check(key: str, state: str | None, note: str | None) -> dict:
    if key not in CHECK_KEYS:
        raise KeyError(key)
    conn = get_connection()
    try:
        if state is None:
            conn.execute("DELETE FROM era_checks WHERE key=?", (key,))
        else:
            conn.execute("INSERT INTO era_checks (key, state, note, updated_at) VALUES (?,?,?,datetime('now')) "
                         "ON CONFLICT(key) DO UPDATE SET state=excluded.state, note=excluded.note, updated_at=excluded.updated_at",
                         (key, state, (note or "").strip()[:500] or None))
        conn.commit()
    finally:
        conn.close()
    return {"key": key, "state": state}


def collect_era(force: bool = False) -> list[dict]:
    """FRED 계열 → market_indicators.era_*. 처음엔 전 이력, 이후 400일. 20시간 캐시."""
    from services.cache_service import is_cached, set_cache
    from pipeline.macro import _public_fred_history
    from pipeline.market_regime import _yf_history
    if is_cached(ERA_CACHE) and not force:
        return [{"key": "era", "status": "skip", "rows": 0}]
    out = []
    conn = get_connection()
    try:
        sources = [(k, sid, label, unit, "FRED") for k, (sid, label, unit) in ERA_SERIES.items()]
        sources += [(k, t, label, unit, "Yahoo") for k, (t, label, unit) in ERA_YAHOO.items()]
        for key, sid, label, unit, origin in sources:
            ind = f"era_{key}"
            have = conn.execute("SELECT COUNT(*) FROM market_indicators WHERE indicator=?", (ind,)).fetchone()[0]
            days = 40000 if have < 100 else 400
            try:
                rows = _public_fred_history(sid, days) if origin == "FRED" else _yf_history(sid, min(days, 365 * 30))
            except Exception as exc:  # noqa: BLE001 — 소스별 보고
                out.append({"key": ind, "status": "error", "rows": 0, "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
                continue
            extra = json.dumps({"source": f"{origin} {sid}", "label": label, "unit": unit})
            conn.executemany("INSERT INTO market_indicators (snapshot_date, indicator, value, extra_json, fetched_at) VALUES (?,?,?,?,datetime('now')) "
                             "ON CONFLICT(snapshot_date, indicator) DO UPDATE SET value=excluded.value, extra_json=excluded.extra_json, fetched_at=excluded.fetched_at",
                             [(d, ind, val, extra) for d, val in rows])
            conn.commit()
            out.append({"key": ind, "status": "ok" if rows else "error", "rows": len(rows), **({} if rows else {"error": "FRED 응답이 비었습니다"})})
    finally:
        conn.close()
    if all(r["status"] == "ok" for r in out):
        set_cache(ERA_CACHE, 20 * 3600)
    return out
