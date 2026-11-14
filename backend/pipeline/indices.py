"""주요 지수 스트립 — 미국·한국·홍콩·일본 지수의 종가·등락률·1Y 추이 (D-110).

- 소스는 **yfinance(무키)** — 이 환경은 유료/키 필요 소스를 쓸 수 없다.
- 저장은 `market_indicators` 재사용(`index_*` 프리픽스 — macro의 `macro_*` 선례).
  market_regime도 ^KS11을 `kospi`로 90일만 담으므로, 1Y가 필요한 여기는 이름을 분리해
  두 기능이 서로의 히스토리 길이에 얽히지 않게 한다.
- GET은 저장분 읽기, 갱신은 cache_service TTL 게이트로 lazy — 주말·휴장에 매 요청 재fetch 안 함.
- 실패는 **degraded로 드러낸다**(조용한 fallback 금지): 얻은 것만 저장하고 못 얻은 지수를 이름으로 보고.
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from database import get_connection
from pipeline.market_regime import _yf_history

# (key, 표시명, yfinance 티커, 지역, 시장)
INDICES: list[tuple[str, str, str, str, str]] = [
    ("sp500", "S&P 500", "^GSPC", "미국", "us"),
    ("nasdaq", "나스닥", "^IXIC", "미국", "us"),
    ("dow", "다우", "^DJI", "미국", "us"),
    ("kospi", "코스피", "^KS11", "한국", "kr"),
    ("kosdaq", "코스닥", "^KQ11", "한국", "kr"),
    ("hsi", "항셍", "^HSI", "홍콩", "hk"),
    ("nikkei", "니케이225", "^N225", "일본", "jp"),
    ("twii", "대만증시", "^TWII", "대만", "tw"),
]

# 시장별 정규장 세션 — (현지 시간대, [(시작, 끝)…]) 현지시각. 점심 휴장이 있는 시장은 2세션.
# **현지 시간대로 판정**하는 이유: 미국장은 KST로 보면 전날 밤~새벽에 걸치고 DST로 1시간 밀린다.
# 현지 기준으로 계산한 뒤 KST로 변환하면 여름/겨울 시간이 자동으로 맞는다.
KST = ZoneInfo("Asia/Seoul")
MARKETS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "us": ("America/New_York", [("09:30", "16:00")]),
    "tw": ("Asia/Taipei", [("09:00", "13:30")]),
    "kr": ("Asia/Seoul", [("09:00", "15:30")]),
    "hk": ("Asia/Hong_Kong", [("09:30", "12:00"), ("13:00", "16:00")]),   # 점심 휴장
    "jp": ("Asia/Tokyo", [("09:00", "11:30"), ("12:30", "15:30")]),        # 점심 휴장
}

BACKFILL_DAYS = 400   # 1Y 추이 확보(휴장일 감안 여유)
TAIL_DAYS = 7         # 히스토리가 이미 있으면 꼬리만 갱신
_MIN_HISTORY = 200    # 이 미만이면 백필로 취급
SPARK_POINTS = 52     # 1Y 스파크라인 목표 점 수(주 단위 수준)
LAG_HOURS = 1         # 다른 지수보다 이만큼 오래된 수집 시각 = 이 지수만 실패한 것으로 본다


def _indicator(key: str) -> str:
    return f"index_{key}"


def market_status(market: str, now: datetime | None = None) -> dict:
    """정규장 개장 여부 + KST 표기 시간대.

    한계: **공휴일은 반영하지 않는다**(주말만) — 시장별 휴장 캘린더가 없다. UI에 그 사실을 노출한다.
    """
    tz_name, sessions = MARKETS[market]
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo(tz_name))
    hhmm = local.strftime("%H:%M")
    is_open = local.weekday() < 5 and any(s <= hhmm < e for s, e in sessions)

    # 현지 세션 경계를 그 날짜 기준으로 KST 변환 → "22:30–05:00"(미국 여름) 같은 표기
    spans = []
    for s, e in sessions:
        conv = []
        for t in (s, e):
            h, m = (int(x) for x in t.split(":"))
            conv.append(local.replace(hour=h, minute=m, second=0, microsecond=0)
                        .astimezone(KST).strftime("%H:%M"))
        spans.append(f"{conv[0]}–{conv[1]}")
    return {"is_open": is_open, "hours_kst": ", ".join(spans), "timezone": tz_name}


def _intraday_latest(conn, key: str, market: str) -> dict | None:
    """index_intraday의 최신 봉 → {trade_date, value, at(UTC 'YYYY-MM-DD HH:MM:SS')}. 표가 없거나 그 지수가 없으면 None.
    trade_date·hhmm은 그 시장 현지 시각이다(pipeline/index_intraday)."""
    try:
        r = conn.execute("SELECT trade_date, hhmm, value FROM index_intraday WHERE key=? "
                         "ORDER BY trade_date DESC, hhmm DESC LIMIT 1", (key,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if not r or r["value"] is None:
        return None
    local = datetime.fromisoformat(f'{r["trade_date"]}T{r["hhmm"]}').replace(tzinfo=ZoneInfo(MARKETS[market][0]))
    return {"trade_date": r["trade_date"], "value": float(r["value"]),
            "at": local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}


def minutes_to_next_open(now: datetime | None = None, horizon: int = 60) -> int | None:
    """horizon분 안에 어느 시장이든 정규장이 열리면 그때까지 남은 분(5분 단위 올림), 없으면 None."""
    now = now or datetime.now(timezone.utc)
    for m in range(5, horizon + 1, 5):
        if any_market_open(now + timedelta(minutes=m)):
            return m
    return None


def any_market_open(now: datetime | None = None) -> bool:
    """하나라도 정규장이 열려 있나 — 폴링·캐시 TTL 결정용."""
    return any(market_status(m, now)["is_open"] for m in MARKETS)


def _stored_count(conn, key: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM market_indicators WHERE indicator=?", (_indicator(key),)).fetchone()["c"]


def snapshot_indices() -> dict:
    """각 지수 종가 히스토리를 fetch → market_indicators 멱등 적재(INSERT OR REPLACE).

    히스토리가 없으면 1Y 백필, 있으면 꼬리만(가벼운 갱신). 개별 실패는 흡수하되 degraded로 보고.
    """
    conn = get_connection()
    plan = {key: (TAIL_DAYS if _stored_count(conn, key) >= _MIN_HISTORY else BACKFILL_DAYS)
            for key, _, _, _, _ in INDICES}
    conn.close()

    fetched: dict[str, list[tuple[str, float]]] = {}
    degraded: list[str] = []
    for key, label, ticker, _region, _market in INDICES:
        try:
            rows = _yf_history(ticker, days=plan[key])
            if rows:
                fetched[key] = rows
            else:
                degraded.append(label)
        except Exception as e:  # noqa: BLE001
            degraded.append(f"{label}({type(e).__name__})")

    conn = get_connection()
    n = 0
    for key, rows in fetched.items():
        for d, v in rows:
            conn.execute(
                "INSERT OR REPLACE INTO market_indicators(snapshot_date, indicator, value, fetched_at) "
                "VALUES (?,?,?,datetime('now'))",
                (d, _indicator(key), v))
            n += 1
    conn.commit()
    conn.close()
    return {"rows": n, "indices": list(fetched.keys()), "degraded": degraded}


def _hours_apart(a: str, b: str) -> float:
    """SQLite datetime 문자열('YYYY-MM-DD HH:MM:SS', UTC) 두 개의 시간 차(시간)."""
    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        return abs((datetime.strptime(b, fmt) - datetime.strptime(a, fmt)).total_seconds()) / 3600
    except ValueError:
        return 0.0


def _downsample(series: list[float], points: int = SPARK_POINTS) -> list[float]:
    """1Y 일별 → 약 points개(마지막 값은 항상 보존 — 최신 위치가 추이의 끝이어야 한다)."""
    if len(series) <= points:
        return series
    step = len(series) / points
    picked = [series[int(i * step)] for i in range(points)]
    if picked[-1] != series[-1]:
        picked[-1] = series[-1]
    return picked


def get_indices() -> dict:
    """저장분에서 종가·전일대비·1Y 추이 + 시장 개장 상태 (LLM 0, 외부 fetch 없음)."""
    now = datetime.now(timezone.utc)
    status = {m: market_status(m, now) for m in MARKETS}
    conn = get_connection()
    items, missing = [], []
    for key, label, _ticker, region, market in INDICES:
        rows = conn.execute(
            "SELECT snapshot_date, value FROM market_indicators WHERE indicator=? "
            "ORDER BY snapshot_date", (_indicator(key),)).fetchall()
        st = status[market]
        base = {"key": key, "label": label, "region": region, "market": market,
                "is_open": st["is_open"], "hours_kst": st["hours_kst"]}
        if not rows:
            missing.append(label)
            items.append({**base, "price": None, "change_pct": None, "spark": [],
                          "as_of": None, "fetched_at": None})
            continue
        # 지수별 최근 수집 시각(UTC) — 한 지수만 실패하면 그 타일만 뒤처지므로 지수별로 보여준다
        fetched_at = conn.execute(
            "SELECT MAX(fetched_at) f FROM market_indicators WHERE indicator=?",
            (_indicator(key),)).fetchone()["f"]
        closes = [r["value"] for r in rows]
        as_of = rows[-1]["snapshot_date"]
        price = closes[-1]
        prev = closes[-2] if len(closes) >= 2 else None
        shown_at = fetched_at
        # 장중엔 정기 수집(index_intraday, launchd 10분)의 최신 봉을 얹는다 — 이 띠만 yfinance 갱신(요청 때 TTL)에 묶여
        # 장 시작 뒤에도 장전 값에 머물던 문제(2026-11-10). Market Today와 같은 원천·같은 템포.
        live = _intraday_latest(conn, key, market) if st["is_open"] else None
        # 봉 날짜가 저장 종가보다 새로우면 수집 시각과 무관하게 얹는다 — 개장 직후 스냅샷이 오늘 일별 행 없이
        # 어제 행의 fetched_at만 늦춰 09:05 봉을 가린 일(2026-11-11)
        if live and (live["trade_date"] > as_of
                     or (live["trade_date"] == as_of and (not fetched_at or live["at"] > fetched_at))):
            if live["trade_date"] > as_of:          # 오늘 일별 행이 아직 없다 → 마지막 저장 종가가 전일 종가
                prev, closes = price, closes + [live["value"]]
            else:
                closes = closes[:-1] + [live["value"]]
            price, as_of, shown_at = live["value"], live["trade_date"], live["at"]
        change_pct = round((price / prev - 1) * 100, 2) if prev else None
        items.append({
            **base,
            "price": price, "change_pct": change_pct,
            "spark": _downsample(closes),
            "as_of": as_of,
            "fetched_at": shown_at,
            "_collected_at": fetched_at,
        })
    conn.close()

    # 뒤처진 지수 = 다른 지수는 갱신됐는데 이것만 옛 수집 시각 → 그 지수만 실패했다는 뜻.
    # 프로세스 상태가 아니라 저장된 데이터에서 파생하므로 서버 재시작에도 살아남는다.
    # 판정은 yfinance 수집 시각으로 — 장중 봉을 얹은 지수의 새 시각과 비교하면 나머지가 뒤처진 것으로 잘못 보인다
    stamps = [it["_collected_at"] for it in items if it.get("_collected_at")]
    newest = max(stamps) if stamps else None
    for it in items:
        collected = it.pop("_collected_at", None)
        it["lagging"] = bool(newest and collected and _hours_apart(collected, newest) > LAG_HOURS)

    dates = [it["as_of"] for it in items if it["as_of"]]
    degraded = missing + [it["label"] for it in items if it["lagging"]]
    return {"as_of": max(dates) if dates else None, "items": items, "missing": missing,
            "degraded": degraded,
            "any_open": any(s["is_open"] for s in status.values()),
            "holiday_aware": False}   # 공휴일 캘린더 없음 — UI에 그대로 노출


def kr_breadth(conn) -> dict | None:
    """국내 시장 폭 — 최근 거래일 종가가 직전 거래일 종가보다 오른·내린·같은 종목 수 (D-321, LLM 0·외부 0).

    `stock_prices` 저장분만 읽는다. 그날 수집이 덜 된 날(최근 날짜 중 최다 종목 수의 절반 미만)은
    건너뛰어, 몇 종목만 들어온 날로 비율이 흔들리지 않게 한다. 비교할 두 날이 없거나
    오르고 내린 종목이 하나도 없으면 None.
    """
    rows = conn.execute(
        "SELECT trade_date, COUNT(*) n FROM stock_prices "
        "WHERE trade_date >= date((SELECT MAX(trade_date) FROM stock_prices), '-20 day') "
        "GROUP BY trade_date ORDER BY trade_date DESC").fetchall()
    if not rows:
        return None
    full = max(r[1] for r in rows)
    days = [r[0] for r in rows if r[1] * 2 >= full]
    if len(days) < 2:
        return None
    day, prev = days[0], days[1]
    up, down, flat = conn.execute(
        "SELECT COALESCE(SUM(a.close > b.close), 0), COALESCE(SUM(a.close < b.close), 0), "
        "COALESCE(SUM(a.close = b.close), 0) "
        "FROM stock_prices a JOIN stock_prices b ON b.stock_code = a.stock_code AND b.trade_date = ? "
        "WHERE a.trade_date = ? AND a.close > 0 AND b.close > 0", (prev, day)).fetchone()
    if up + down == 0:
        return None
    return {"trade_date": day, "prev_date": prev, "up": up, "down": down, "flat": flat,
            "up_ratio": round(up / (up + down), 4)}
