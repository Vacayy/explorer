"""홈 › 한국 시장 · 미국 시장 ① 지수 차트 + 요약 지표 4칸 (ia-redesign §4.2·4.3, D-325).

저장분만 읽는다(LLM 0, 외부 호출 0):
- 1일 경로: `index_intraday`(pipeline/index_intraday, 5분봉). 마감 뒤에는 저장 일별 종가를 마감 시각 점으로 붙인다
  (yfinance 5분봉은 마지막 30분가량이 늦게 들어온다).
- 전일 종가·기간 차트: `market_indicators` `index_*` 일별 종가(지수 띠와 같은 원천). yfinance 일봉은 하루가 빠질 때가 있어
  전일 기준은 저장분을 쓴다(market_today 1cb2c564와 같은 이유).
- 요약 지표: 한국 = 시장 폭(`stock_prices`, D-321) · 개인 순매수(`retail_flows`) · 달러/원(`macro_usdkrw`) ·
  신용융자(`retail_flows.credit_total`, 20일 변화율의 5년 백분위는 개인 투자 열기와 같은 계산) /
  미국 = 공포·탐욕(`risk_fear_greed`) · 미 10년(`risk_us10y`, 2년 병기) · DXY(`macro_dxy`) · WTI(`macro_oil`).
시장 폭은 전 종목 비교(~0.4초)라 10분 메모한다 — 나머지는 색인 범위 조회라 매번 읽는다.
"""
import time
from bisect import bisect_left
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from pipeline.index_intraday import SESSIONS
from pipeline.indices import kr_breadth
from pipeline import retail_heat as rh

KST = ZoneInfo("Asia/Seoul")
INDEX_NAMES = {"kr": [("kospi", "코스피"), ("kosdaq", "코스닥")],
               "us": [("sp500", "S&P 500"), ("nasdaq", "나스닥"), ("dow", "다우")]}
RANGE_DAYS = {"1m": 21, "3m": 63, "1y": 250}   # 일봉 개수(약 1개월·3개월·1년)
SERIES_N = 20
BREADTH_TTL = 10 * 60
_breadth_memo: tuple[float, dict | None] | None = None


def _hm_minutes(hm: str) -> int:
    return int(hm[:2]) * 60 + int(hm[3:5])


def _index(conn, market: str, key: str, name: str, now: datetime) -> dict:
    tz, open_, close_ = SESSIONS[market]
    local = now.astimezone(ZoneInfo(tz))
    today = local.date().isoformat()
    minutes = local.hour * 60 + local.minute
    weekday = local.weekday() < 5

    daily = [(r[0], r[1]) for r in reversed(conn.execute(
        "SELECT snapshot_date, value FROM market_indicators WHERE indicator=? AND value IS NOT NULL "
        "ORDER BY snapshot_date DESC LIMIT ?", (f"index_{key}", RANGE_DAYS["1y"] + 5)).fetchall())]
    last_intraday = conn.execute("SELECT MAX(trade_date) FROM index_intraday WHERE key=?", (key,)).fetchone()[0]
    day = max(filter(None, [last_intraday, daily[-1][0] if daily else None]), default=None)

    if day == today and weekday and minutes >= _hm_minutes(open_):
        state = "open" if minutes <= _hm_minutes(close_) else "closed"
    elif weekday and minutes < _hm_minutes(open_) and (day or "") < today:
        state = "pre"
    else:
        state = "closed"

    path = [(r[0], r[1]) for r in conn.execute(
        "SELECT hhmm, value FROM index_intraday WHERE key=? AND trade_date=? AND value IS NOT NULL ORDER BY hhmm",
        (key, day)).fetchall()] if day else []
    day_close = next((v for d, v in reversed(daily) if d == day), None)
    if state != "open" and day_close is not None and (not path or path[-1][0] < close_):
        path.append((close_, day_close))   # 마감 — 저장 종가를 마감 시각 점으로
    if state == "open":
        value, last_time = (path[-1][1], path[-1][0]) if path else (day_close, None)
    else:
        value = day_close if day_close is not None else (path[-1][1] if path else None)
        last_time = close_ if day_close is not None else (path[-1][0] if path else None)

    prev_close = next((v for d, v in reversed(daily) if day and d < day), None)
    change = round(value - prev_close, 2) if value is not None and prev_close else None
    change_pct = round((value / prev_close - 1) * 100, 2) if value is not None and prev_close else None
    last_kst = None
    if day and last_time:
        at = datetime.combine(date.fromisoformat(day), datetime.strptime(last_time, "%H:%M").time(), ZoneInfo(tz))
        last_kst = at.astimezone(KST).strftime("%Y-%m-%d %H:%M")

    # 기간 차트의 마지막 점은 1일 값과 맞춘다(장중이면 지금 값)
    closes = list(daily)
    if day and value is not None:
        if closes and closes[-1][0] == day:
            closes[-1] = (day, value)
        elif not closes or closes[-1][0] < day:
            closes.append((day, value))
    ranges = [{"key": "1d", "base": prev_close, "points": [{"t": t, "v": v} for t, v in path]}]
    for rk, n in RANGE_DAYS.items():
        seg = closes[-(n + 1):]
        ranges.append({"key": rk, "base": seg[0][1] if len(seg) > n else None,
                       "points": [{"t": d, "v": v} for d, v in seg[-n:]]})
    return {"key": key, "name": name, "value": value, "change": change, "change_pct": change_pct, "prev_close": prev_close,
            "session": {"state": state, "trade_date": day, "last_time": last_time, "last_kst": last_kst, "open": open_, "close": close_},
            "ranges": ranges}


def _series(conn, indicator: str, n: int = SERIES_N + 1) -> list[tuple[str, float]]:
    rows = conn.execute("SELECT snapshot_date, value FROM market_indicators WHERE indicator=? AND value IS NOT NULL "
                        "ORDER BY snapshot_date DESC LIMIT ?", (indicator, n)).fetchall()
    return [(r[0], r[1]) for r in reversed(rows)]


def _line_tile(conn, key: str, label: str, indicator: str) -> dict:
    s = _series(conn, indicator)
    last = s[-1] if s else None
    prev = s[-2][1] if len(s) >= 2 else None
    return {"key": key, "label": label, "value": last[1] if last else None, "as_of": last[0] if last else None,
            "change_pct": round((last[1] / prev - 1) * 100, 2) if last and prev else None,
            "series": [v for _, v in s[-SERIES_N:]]}


def _breadth(conn) -> dict | None:
    global _breadth_memo
    if _breadth_memo and time.monotonic() - _breadth_memo[0] < BREADTH_TTL:
        return _breadth_memo[1]
    value = kr_breadth(conn)
    _breadth_memo = (time.monotonic(), value)
    return value


def _credit(conn) -> dict:
    """신용융자 — 최근 값·20일 추이, 20영업일 변화율과 그 5년 백분위(retail_heat.series·with_percentiles와 같은 정의).

    변화율은 retail_flows 행 위치로 20행 전과 비교한다(한국거래소 개인 거래만 들어온 날도 한 행). 꼬리만 읽는다.
    """
    rows = [dict(r) for r in reversed(conn.execute(
        "SELECT date, credit_total FROM retail_flows ORDER BY date DESC LIMIT ?",
        (rh.PCTILE_DAYS + 4 * rh.WINDOW + 200,)).fetchall())]
    growth = []
    for i, r in enumerate(rows):
        prev = rows[i - rh.WINDOW] if i >= rh.WINDOW else None
        a, b = r["credit_total"], prev["credit_total"] if prev else None
        growth.append((a - b) / b if a is not None and b else None)
    valid = [(i, g) for i, g in enumerate(growth) if g is not None]
    pctile = g20 = None
    if valid:
        i_last, g20 = valid[-1]
        history = [g for _, g in valid[:-1]][-rh.PCTILE_DAYS:]
        if len(history) >= rh.MIN_PCTILE_DAYS:
            pctile = round(bisect_left(sorted(history), g20) / len(history) * 100, 1)
    levels = [(r["date"], r["credit_total"]) for r in rows if r["credit_total"] is not None]
    last = levels[-1] if levels else None
    prev = levels[-2][1] if len(levels) >= 2 else None
    return {"key": "credit", "label": "신용융자", "value": last[1] if last else None, "as_of": last[0] if last else None,
            "change_pct": round((last[1] / prev - 1) * 100, 2) if last and prev else None,
            "series": [v for _, v in levels[-SERIES_N:]], "growth_20": g20, "pctile": pctile}


def _indiv(conn) -> dict:
    rows = [dict(r) for r in reversed(conn.execute(
        "SELECT date, indiv_buy, indiv_sell FROM retail_flows WHERE indiv_buy IS NOT NULL AND indiv_sell IS NOT NULL "
        "ORDER BY date DESC LIMIT ?", (SERIES_N,)).fetchall())]
    last = rows[-1] if rows else None
    return {"key": "indiv_net", "label": "개인 순매수", "value": last["indiv_buy"] - last["indiv_sell"] if last else None,
            "as_of": last["date"] if last else None, "change_pct": None,
            "series": [r["indiv_buy"] - r["indiv_sell"] for r in rows], "buy": last["indiv_buy"] if last else None,
            "sell": last["indiv_sell"] if last else None}


def _kr_tiles(conn) -> list[dict]:
    b = _breadth(conn)
    breadth = {"key": "breadth", "label": "시장 폭", "value": b["up_ratio"] if b else None, "as_of": b["trade_date"] if b else None,
               "change_pct": None, "series": [], "up": b["up"] if b else None, "down": b["down"] if b else None,
               "flat": b["flat"] if b else None}
    return [breadth, _indiv(conn), _line_tile(conn, "usdkrw", "달러/원", "macro_usdkrw"), _credit(conn)]


def _us_tiles(conn) -> list[dict]:
    us10 = _line_tile(conn, "us10y", "미 10년 금리", "risk_us10y")
    us2 = _series(conn, "risk_us2y", 1)
    us10["second"] = us2[-1][1] if us2 else None
    return [_line_tile(conn, "fear_greed", "공포·탐욕", "risk_fear_greed"), us10,
            _line_tile(conn, "dxy", "달러 DXY", "macro_dxy"), _line_tile(conn, "wti", "WTI", "macro_oil")]


def overview(conn, market: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    indices = [_index(conn, market, key, name, now) for key, name in INDEX_NAMES[market]]
    tiles = _kr_tiles(conn) if market == "kr" else _us_tiles(conn)
    return {"market": market, "indices": indices, "tiles": tiles}
