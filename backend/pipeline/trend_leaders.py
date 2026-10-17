"""가파른 추세 종목 — 빠르게 오르면서 '추세'라 부를 만큼 고르게 오른 국내 종목 (LLM 0·네트워크 0).

급등(하루 이틀 튄 것)과 추세를 가르는 게 핵심이다. 조건은 모두 AND:
- 규모: 시총 3,000억 이상 (유동성·정보 커버리지)
- 가파름: 60거래일 수익률 +30% 이상
- 고름: 60거래일 log(종가) 회귀의 R² 0.75 이상 — 한 번 튄 상승은 R²가 낮다
- 정배열: 종가 > MA20 > MA60, MA60이 20거래일 전보다 높다
- 강도: ADX(14) 25 이상이고 +DI > −DI (strategies._adx 재사용)
순위 = 연율 로그 기울기 × R² (Clenow식 '추세의 질'). 5거래일 전엔 조건 밖이었으면 new.
stock_prices 최신일 기준으로 계산해 프로세스 메모리에 둔다(시세가 바뀌면 다시 계산).
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
HISTORY = 160          # ADX 평활이 수렴하고 MA60을 20일 전과 비교할 만큼
LIMIT = 20

CRITERIA = (f"시총 3,000억+ · {WINDOW}거래일 +{MIN_RET:.0f}%+ · 상승 고름 R² {MIN_R2}+ · "
            f"종가>MA20>MA60(MA60 상승) · ADX {MIN_ADX:.0f}+(+DI>−DI)")

_cache: dict[str, dict] = {}


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
    return {
        "ret_20": round((closes[end] / closes[end - 20] - 1) * 100, 1),
        "ret_60": round(ret60, 1),
        "r2": round(r2, 2),
        "adx": round(a, 1),
        "gap_ma20": round((closes[end] / ma20 - 1) * 100, 1),
        "score": round(slope * 250 * 100 * r2, 1),   # 연율 로그 기울기(%) × R² — 정렬 기준
    }


def compute() -> dict:
    conn = get_connection()
    try:
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT trade_date FROM stock_prices ORDER BY trade_date DESC LIMIT ?", (HISTORY,))]
        if not dates:
            return {"as_of": None, "criteria": CRITERIA, "universe": 0, "items": []}
        as_of = dates[0]
        if as_of in _cache:
            return _cache[as_of]
        latest = {r["stock_code"]: r for r in conn.execute(
            "SELECT sp.stock_code, sp.market_cap, c.corp_name FROM stock_prices sp JOIN companies c ON c.stock_code = sp.stock_code "
            "WHERE sp.trade_date = ? AND sp.market_cap >= ?", (as_of, MIN_MCAP))}
        series: dict[str, list[dict]] = {code: [] for code in latest}
        for r in conn.execute(
                "SELECT stock_code, high, low, close FROM stock_prices WHERE trade_date >= ? AND close IS NOT NULL "
                "ORDER BY stock_code, trade_date", (dates[-1],)):
            if r["stock_code"] in series and r["high"] is not None and r["low"] is not None:
                series[r["stock_code"]].append({"high": r["high"], "low": r["low"], "close": r["close"]})
        sectors = _members(conn)
    finally:
        conn.close()

    items = []
    for code, rows in series.items():
        hit = evaluate(rows, len(rows) - 1)
        if not hit:
            continue
        items.append({
            "stock_code": code, "name": latest[code]["corp_name"], "sector": sectors.get(code),
            "market_cap": latest[code]["market_cap"], "close": rows[-1]["close"], **hit,
            "new": evaluate(rows, len(rows) - 1 - NEW_LAG) is None,
            "spark": [r["close"] for r in rows[-WINDOW:]],
        })
    items.sort(key=lambda x: x["score"], reverse=True)
    result = {"as_of": as_of, "criteria": CRITERIA, "universe": len(latest), "passed": len(items), "items": items[:LIMIT]}
    _cache.clear()
    _cache[as_of] = result
    return result
