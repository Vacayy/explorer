"""지수 장중 5분 경로 수집 (ia-redesign §4.2·4.3 ① 지수 차트, D-325).

- 원천은 yfinance 5분봉(무키): ^KS11·^KQ11(국장 09:00–15:30 KST), ^GSPC·^IXIC·^DJI(미장 정규장 09:30–16:00 ET).
- 저장은 `index_intraday(market, key, trade_date, hhmm, value)` — trade_date·hhmm은 **그 시장의 현지 시각**(미국은 ET).
  같은 (key, trade_date, hhmm)은 덮어쓴다(멱등). 늦게 들어온 봉이 앞선 값을 고친다.
- launchd `indexintraday`가 10분마다 부른다. 장 밖·주말이면 외부 호출 없이 바로 끝난다(`due_markets`).
  공휴일 달력은 없다 — 평일 장 시간에 휴장이면 yfinance가 그날 봉을 주지 않아 아무것도 저장되지 않는다.
- GET(`/api/spine/market/{kr|us}/overview`)은 이 표의 저장분만 읽는다. 요청 중 외부 호출 금지(api-performance §1).
- Market Today 회차가 쌓아 둔 코스피 경로(`market_today.market_json.path`)도 비어 있는 자리에 채운다(`seed_from_market_today`).
"""
import json
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo

from database import get_connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS index_intraday (
    market     TEXT NOT NULL,   -- kr | us
    key        TEXT NOT NULL,   -- kospi | kosdaq | sp500 | nasdaq | dow (market_indicators index_{key}와 같은 키)
    trade_date TEXT NOT NULL,   -- 현지 거래일 YYYY-MM-DD (미국 = ET)
    hhmm       TEXT NOT NULL,   -- 현지 봉 시작 시각 HH:MM
    value      REAL,
    PRIMARY KEY (key, trade_date, hhmm)
);
"""

# (key, 시장, yfinance 티커)
TICKERS: list[tuple[str, str, str]] = [
    ("kospi", "kr", "^KS11"),
    ("kosdaq", "kr", "^KQ11"),
    ("sp500", "us", "^GSPC"),
    ("nasdaq", "us", "^IXIC"),
    ("dow", "us", "^DJI"),
]
# 시장별 (시간대, 개장, 마감) — 현지 시각
SESSIONS: dict[str, tuple[str, str, str]] = {
    "kr": ("Asia/Seoul", "09:00", "15:30"),
    "us": ("America/New_York", "09:30", "16:00"),
}
# 마감 뒤 늦게 들어오는 마지막 봉을 받으려고 이만큼 더 돈다(분)
GRACE_MIN = 20


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def _hm(s: str) -> dtime:
    return dtime(int(s[:2]), int(s[3:5]))


def due_markets(now: datetime | None = None) -> list[str]:
    """지금 수집할 시장 — 현지 평일 개장~마감+여유 사이. 장 밖이면 빈 목록(외부 호출 없음)."""
    now = now or datetime.now(timezone.utc)
    out = []
    for market, (tz, start, end) in SESSIONS.items():
        local = now.astimezone(ZoneInfo(tz))
        if local.weekday() >= 5:
            continue
        mins = local.hour * 60 + local.minute
        s, e = _hm(start), _hm(end)
        if s.hour * 60 + s.minute <= mins <= e.hour * 60 + e.minute + GRACE_MIN:
            out.append(market)
    return out


def _bars(ticker: str, market: str, period: str) -> list[tuple[str, str, float]]:
    """yfinance 5분봉 → [(현지 날짜, HH:MM, 종가)] — 정규장 안의 봉만."""
    import yfinance as yf
    tz, start, end = SESSIONS[market]
    zone = ZoneInfo(tz)
    s, e = _hm(start), _hm(end)
    closes = yf.Ticker(ticker).history(period=period, interval="5m")["Close"].dropna()
    out = []
    for idx, v in closes.items():
        t = idx.to_pydatetime().astimezone(zone)
        if s <= t.time() <= e:
            out.append((t.date().isoformat(), t.strftime("%H:%M"), round(float(v), 2)))
    return out


def store(conn, market: str, key: str, rows: list[tuple[str, str, float]], replace: bool = True) -> int:
    ensure_schema(conn)
    verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    before = conn.total_changes
    conn.executemany(f"{verb} INTO index_intraday(market, key, trade_date, hhmm, value) VALUES (?,?,?,?,?)",
                     [(market, key, d, hm, v) for d, hm, v in rows])
    return conn.total_changes - before


def collect(markets: list[str] | None = None, period: str = "1d") -> dict:
    """대상 시장의 5분봉을 받아 적재. period='5d'면 최근 5거래일 백필. 실패한 지수는 이름으로 보고(degraded)."""
    markets = markets if markets is not None else due_markets()
    if not markets:
        return {"status": "skipped", "reason": "장 밖", "rows": 0}
    fetched: dict[str, tuple[str, list]] = {}
    degraded = []
    for key, market, ticker in TICKERS:
        if market not in markets:
            continue
        try:
            rows = _bars(ticker, market, period)
        except Exception as e:  # noqa: BLE001
            degraded.append(f"{key}({type(e).__name__})")
            continue
        if rows:
            fetched[key] = (market, rows)
        else:
            degraded.append(f"{key}(봉 없음)")
    conn = get_connection()
    try:
        n = sum(store(conn, market, key, rows) for key, (market, rows) in fetched.items())
        n += seed_from_market_today(conn)
        conn.commit()
    finally:
        conn.close()
    # 봉이 하나도 없으면 휴장(skipped), 예외로 못 받았으면 error
    status = "ok" if fetched else "error" if any("봉 없음" not in d for d in degraded) else "skipped"
    return {"status": status, "rows": n, "markets": markets, "indices": list(fetched), "degraded": degraded}


def seed_from_market_today(conn) -> int:
    """Market Today 회차의 코스피 5분 경로로 빈 자리를 채운다(yfinance 값이 있으면 그대로 둔다).

    날마다 가장 긴 경로(늦은 회차)를 쓴다. market_today 표가 없으면 0.
    """
    ensure_schema(conn)
    try:
        rows = conn.execute("SELECT trade_date, market_json FROM market_today WHERE market_json IS NOT NULL").fetchall()
    except Exception:  # noqa: BLE001 — 표가 없는 DB(테스트·새 설치)
        return 0
    best: dict[str, list] = {}
    for r in rows:
        try:
            path = (json.loads(r[1]) or {}).get("path") or []
        except (TypeError, ValueError):
            continue
        if len(path) > len(best.get(r[0], [])):
            best[r[0]] = path
    n = 0
    s, e = SESSIONS["kr"][1], SESSIONS["kr"][2]
    for day, path in best.items():
        pts = [(day, hm, float(v)) for hm, v in path if isinstance(hm, str) and s <= hm <= e and v is not None]
        n += store(conn, "kr", "kospi", pts, replace=False)
    return n
