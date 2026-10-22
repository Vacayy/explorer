"""가파른 추세 종목 — 빠르게 오르면서 '추세'라 부를 만큼 고르게 오른 국내 종목 (LLM 0·네트워크 0).

급등(하루 이틀 튄 것)과 추세를 가르는 게 핵심이다. 조건은 모두 AND:
- 규모: 시총 3,000억 이상 (유동성·정보 커버리지)
- 가파름: 60거래일 수익률 +30% 이상
- 고름: 60거래일 log(종가) 회귀의 R² 0.75 이상 — 한 번 튄 상승은 R²가 낮다
- 정배열: 종가 > MA20 > MA60, MA60이 20거래일 전보다 높다
- 강도: ADX(14) 25 이상이고 +DI > −DI (strategies._adx 재사용)
순위 = 연율 로그 기울기 × R² (Clenow식 '추세의 질'). 5거래일 전엔 조건 밖이었으면 new.
종목마다 근거(evidence: 조건별 실제 값·60일 회귀선)를 함께 돌려준다. 근거 창 차트(2년)는 `chart(code)`가 따로 준다.

52주 신고가 단계(추세 통과 종목, `high52`):
- breakout: 최근 5거래일 안에 종가가 직전 250거래일 최고가(전고점)를 처음 넘었다
- retest: 60거래일 안에 전고점(20거래일 넘게 신고가가 없던 뒤 처음 넘은 직전 250거래일 최고가)을 돌파 → 돌파선 근처(저가 −5%~+3%)까지 되돌림, 그동안 종가가 돌파선 −3% 아래로 안 빠졌고
  → 그 저점 뒤 다시 올라 오늘 종가가 돌파선과 되돌림 날 종가 위

이벤트(같은 모집단, 추세 조건과 별개):
- 52주 신고가 돌파: 최근 5거래일 안에 종가가 직전 250거래일 고가 최고치를 처음 넘었다
- 매물대 돌파 후 지지: 20거래일 전까지 250거래일의 최대 매물대(종가·거래량 20구간 POC) 윗선을
  최근 20거래일 안에 종가로 돌파(돌파 뒤 2거래일 이상) → 되돌림 저가가 그 선 −2%~+3% 안에서 멈췄고(종가 이탈 없음) 오늘 종가가 선 위

정해진 시각에 도는 잡이 아니다. GET 때 stock_prices로 계산하고, (최신 거래일, 그날 행의 최신 fetched_at)이
같으면 메모리 캐시를 쓴다 — 시세 수집(평일 16:35·20:20 재수집)이 끝나면 다음 조회에서 다시 계산된다.
"""
import math

from database import get_connection
from pipeline.market_analysis.strategies import _adx
from pipeline.sector_rs import _members

MIN_MCAP = 300_000_000_000
WINDOW = 60
MIN_RET = 30.0
MIN_R2 = 0.75
MIN_ADX = 25.0
NEW_LAG = 5
HISTORY = 340          # 52주(250) 신고가 + 지지 확인 60일·매물대(250+20)·ADX 평활 수렴에 충분히
CHART_DAYS = 500       # 근거 창 차트 ≈ 2년
HIGH_LOOKBACK = 250
EVENT_DAYS = 5         # 신고가 돌파를 '최근'으로 보는 기간
VP_BASE, VP_RECENT, VP_BINS = 250, 20, 20
VP_LOW, VP_HIGH = 0.98, 1.03   # 되돌림 저가가 멈춰야 하는 범위(돌파선 대비)
RETEST_DAYS = 60                # 신고가 돌파 후 지지·재반등을 보는 기간
RETEST_HOLD = 0.97              # 돌파 뒤 종가가 이 아래(돌파선 대비)로 빠지면 지지 실패
RETEST_LOW, RETEST_HIGH = 0.95, 1.03   # 되돌림 저점이 돌파선 근처라고 보는 범위
BASE_QUIET = 20                 # 이만큼 신고가가 없다가 처음 넘은 날 = 전고점 돌파일
LIMIT = 20

CRITERIA = (f"시총 3,000억+ · {WINDOW}거래일 +{MIN_RET:.0f}%+ · 상승 고름 R² {MIN_R2}+ · "
            f"종가>MA20>MA60(MA60 상승) · ADX {MIN_ADX:.0f}+(+DI>−DI)")

_cache: dict[tuple, dict] = {}


def _ma(closes: list[float], end: int, n: int) -> float | None:
    """closes[end-n+1 .. end] 평균"""
    if end + 1 < n:
        return None
    return sum(closes[end - n + 1:end + 1]) / n


def _fit(closes: list[float]) -> tuple[float, float]:
    """log(종가)의 최소제곱 직선 → (일 기울기, R²)"""
    ys = [math.log(c) for c in closes]
    n = len(ys)
    mx, my = (n - 1) / 2, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in range(n))
    sxy = sum((x - mx) * (y - my) for x, y in zip(range(n), ys))
    slope = sxy / sxx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (my + slope * (x - mx))) ** 2 for x, y in zip(range(n), ys))
    return slope, (1 - ss_res / ss_tot) if ss_tot > 0 else 0.0


def evaluate(rows: list[dict], end: int) -> dict | None:
    """rows[end] 시점에 조건을 모두 통과하면 지표를, 아니면 None"""
    if end < WINDOW + 20 or end >= len(rows):
        return None
    closes = [r["close"] for r in rows]
    win = closes[end - WINDOW:end + 1]
    if min(win) <= 0:
        return None
    ret60 = (win[-1] / win[0] - 1) * 100
    if ret60 < MIN_RET:
        return None
    ma20, ma60, ma60_prev = _ma(closes, end, 20), _ma(closes, end, 60), _ma(closes, end - 20, 60)
    if None in (ma20, ma60, ma60_prev) or not (closes[end] > ma20 > ma60 and ma60 > ma60_prev):
        return None
    slope, r2 = _fit(win)
    if r2 < MIN_R2:
        return None
    adx = _adx(rows[:end + 1], 14)
    a, p, m = adx["adx"][end], adx["plus_di"][end], adx["minus_di"][end]
    if a is None or a < MIN_ADX or p is None or m is None or p <= m:
        return None
    n = len(win)
    start = math.exp(sum(math.log(c) for c in win) / n - slope * (n - 1) / 2)   # 회귀선의 시작점(가격)
    return {
        "evidence": {
            "close": closes[end], "ma20": round(ma20, 2), "ma60": round(ma60, 2), "ma60_prev": round(ma60_prev, 2),
            "plus_di": round(p, 1), "minus_di": round(m, 1),
            "fit_start": round(start, 2), "fit_end": round(start * math.exp(slope * (n - 1)), 2),
        },
        "ret_20": round((closes[end] / closes[end - 20] - 1) * 100, 1),
        "ret_60": round(ret60, 1),
        "r2": round(r2, 2),
        "adx": round(a, 1),
        "gap_ma20": round((closes[end] / ma20 - 1) * 100, 1),
        "score": round(slope * 250 * 100 * r2, 1),   # 연율 로그 기울기(%) × R² — 정렬 기준
    }


def _series_ma(closes: list[float], n: int) -> list[float | None]:
    out, run = [], 0.0
    for i, c in enumerate(closes):
        run += c
        if i >= n:
            run -= closes[i - n]
        out.append(round(run / n, 2) if i >= n - 1 else None)
    return out


def high_52w(rows: list[dict]) -> dict | None:
    """최근 EVENT_DAYS 안에 종가가 직전 250거래일 고가 최고치를 처음 넘은 날"""
    for i in range(len(rows) - 1, max(HIGH_LOOKBACK, len(rows) - EVENT_DAYS) - 1, -1):
        level = max(r["high"] for r in rows[i - HIGH_LOOKBACK:i])
        if rows[i]["close"] > level >= rows[i - 1]["close"]:
            return {"kind": "high52", "date": rows[i]["date"], "level": level,
                    "held": rows[-1]["close"] >= level,
                    "detail": f"직전 250거래일 최고가 {level:,.0f} 돌파"}
    return None


def high52_stage(rows: list[dict]) -> dict | None:
    """52주 신고가 단계 — breakout(최근 5거래일 신고가) · retest(60거래일 안 전고점 돌파 → 돌파선 근처 되돌림에서 지지 → 재반등).
    오르는 동안은 매일이 '직전 250거래일 최고가 돌파'라, retest의 돌파선은 20거래일 넘게 신고가가 없던 뒤의 첫 돌파(= 깨진 전고점)로 잡는다."""
    last = len(rows) - 1
    first = max(HIGH_LOOKBACK, last - RETEST_DAYS - BASE_QUIET)
    levels = {i: max(r["high"] for r in rows[i - HIGH_LOOKBACK:i]) for i in range(first, last + 1)}
    cross = [i for i in levels if rows[i]["close"] > levels[i]]
    if not cross:
        return None
    if last - cross[-1] < EVENT_DAYS:
        i = cross[-1]
        return {"kind": "breakout", "date": rows[i]["date"], "level": round(levels[i], 2),
                "detail": f"{rows[i]['date'][5:]} 직전 250거래일 최고가 {levels[i]:,.0f} 돌파"}
    base = [i for i in cross if i >= last - RETEST_DAYS and not any(i - BASE_QUIET <= j < i for j in cross)]
    if not base:
        return None
    i = base[-1]
    level = levels[i]
    after = rows[i + 1:]
    if any(r["close"] < level * RETEST_HOLD for r in after):
        return None
    k = min(range(len(after)), key=lambda j: after[j]["low"])
    touch = after[k]
    if not (level * RETEST_LOW <= touch["low"] <= level * RETEST_HIGH) or k == len(after) - 1:
        return None
    if rows[-1]["close"] <= max(level, touch["close"]):
        return None
    return {"kind": "retest", "date": rows[i]["date"], "level": round(level, 2), "touch_date": touch["date"], "touch_low": touch["low"],
            "detail": f"{rows[i]['date'][5:]} 전고점 {level:,.0f} 돌파 → {touch['date'][5:]} 저가 {touch['low']:,.0f}"
                      f"(돌파선 {(touch['low'] / level - 1) * 100:+.1f}%)에서 지지 → 지금 돌파선 {(rows[-1]['close'] / level - 1) * 100:+.1f}%"}


def chart(code: str, days: int = CHART_DAYS) -> dict:
    """근거 창 차트 — 최근 days거래일 종가·MA20·MA60·52주 고점선(직전 250거래일 최고가 = 그날의 돌파선)"""
    conn = get_connection()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT trade_date date, high, close FROM stock_prices WHERE stock_code=? AND close IS NOT NULL "
            "ORDER BY trade_date DESC LIMIT ?", (code, days + HIGH_LOOKBACK))][::-1]
    finally:
        conn.close()
    closes = [r["close"] for r in rows]
    highs = [r["high"] if r["high"] is not None else r["close"] for r in rows]
    start = max(0, len(rows) - days)
    ma20, ma60 = _series_ma(closes, 20), _series_ma(closes, 60)
    return {"stock_code": code, "dates": [r["date"] for r in rows[start:]], "closes": closes[start:],
            "ma20": ma20[start:], "ma60": ma60[start:],
            "high52": [max(highs[i - HIGH_LOOKBACK:i]) if i >= HIGH_LOOKBACK else None for i in range(start, len(rows))]}


def volume_node_retest(rows: list[dict]) -> dict | None:
    """최대 매물대 윗선 돌파 → 그 선 근처까지 되돌림 → 종가 이탈 없이 위에서 마감"""
    if len(rows) < VP_BASE + VP_RECENT + 1:
        return None
    base = rows[-(VP_BASE + VP_RECENT):-VP_RECENT]
    lo, hi = min(r["close"] for r in base), max(r["close"] for r in base)
    if hi <= lo:
        return None
    width = (hi - lo) / VP_BINS
    buckets = [0.0] * VP_BINS
    for r in base:
        buckets[min(int((r["close"] - lo) / width), VP_BINS - 1)] += r["volume"] or 0
    total = sum(buckets) or 1
    poc = max(range(VP_BINS), key=lambda i: buckets[i])
    level = lo + (poc + 1) * width            # 매물대 윗선
    recent = rows[-VP_RECENT - 1:]
    for k in range(1, len(recent) - 2):        # 돌파 뒤 최소 2거래일은 지켜봐야 '지지'라 부른다
        if not (recent[k - 1]["close"] <= level < recent[k]["close"]):
            continue
        after = recent[k + 1:]
        if any(r["close"] < level * VP_LOW for r in after):
            return None
        touch = min(after, key=lambda r: r["low"])
        if not (level * VP_LOW <= touch["low"] <= level * VP_HIGH) or rows[-1]["close"] <= level:
            return None
        return {"kind": "vp_retest", "date": recent[k]["date"], "level": round(level, 2), "held": True,
                "detail": f"매물대({lo + poc * width:,.0f}~{level:,.0f}, 거래량 {buckets[poc] / total * 100:.0f}%) 윗선 돌파 → "
                          f"{touch['date'][5:]} 저가 {touch['low']:,.0f}에서 지지"}
    return None


def compute() -> dict:
    conn = get_connection()
    try:
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT trade_date FROM stock_prices ORDER BY trade_date DESC LIMIT ?", (HISTORY,))]
        if not dates:
            return {"as_of": None, "criteria": CRITERIA, "universe": 0, "items": []}
        as_of = dates[0]
        stamp = conn.execute("SELECT max(fetched_at) FROM stock_prices WHERE trade_date = ?", (as_of,)).fetchone()[0]
        if (as_of, stamp) in _cache:
            return _cache[(as_of, stamp)]
        latest = {r["stock_code"]: r for r in conn.execute(
            "SELECT sp.stock_code, sp.market_cap, c.corp_name FROM stock_prices sp JOIN companies c ON c.stock_code = sp.stock_code "
            "WHERE sp.trade_date = ? AND sp.market_cap >= ?", (as_of, MIN_MCAP))}
        series: dict[str, list[dict]] = {code: [] for code in latest}
        for r in conn.execute(
                "SELECT stock_code, trade_date, high, low, close, volume FROM stock_prices WHERE trade_date >= ? AND close IS NOT NULL "
                "ORDER BY stock_code, trade_date", (dates[-1],)):
            if r["stock_code"] in series and r["high"] is not None and r["low"] is not None:
                series[r["stock_code"]].append({"date": r["trade_date"], "high": r["high"], "low": r["low"],
                                                "close": r["close"], "volume": r["volume"]})
        sectors = _members(conn)
    finally:
        conn.close()

    items, events = [], []
    for code, rows in series.items():
        base = {"stock_code": code, "name": latest[code]["corp_name"], "sector": sectors.get(code)}
        found = [e for e in (high_52w(rows), volume_node_retest(rows)) if e]
        events += [{**base, "close": rows[-1]["close"], **e} for e in found]
        hit = evaluate(rows, len(rows) - 1)
        if not hit:
            continue
        items.append({
            **base, "market_cap": latest[code]["market_cap"], "close": rows[-1]["close"], **hit,
            "new": evaluate(rows, len(rows) - 1 - NEW_LAG) is None,
            "events": [e["kind"] for e in found],
            "high52": high52_stage(rows),
            "spark": [r["close"] for r in rows[-WINDOW:]],
        })
    items.sort(key=lambda x: x["score"], reverse=True)
    events.sort(key=lambda e: (e["date"], e["kind"]), reverse=True)
    # 상위 20 + 신고가 단계가 붙은 종목은 순위 밖이어도 싣는다(따로 골라 보게)
    shown = items[:LIMIT] + [i for i in items[LIMIT:] if i["high52"]]
    result = {"as_of": as_of, "computed_from": stamp, "criteria": CRITERIA, "universe": len(latest),
              "passed": len(items), "items": shown, "events": events}
    _cache.clear()
    _cache[(as_of, stamp)] = result
    return result
