"""주요 지수 스트립 — 미국·한국·홍콩·일본 지수의 종가·등락률·1Y 추이 (D-110).

- 소스는 **yfinance(무키)** — 이 환경은 유료/키 필요 소스를 쓸 수 없다.
- 저장은 `market_indicators` 재사용(`index_*` 프리픽스 — macro의 `macro_*` 선례).
  market_regime도 ^KS11을 `kospi`로 90일만 담으므로, 1Y가 필요한 여기는 이름을 분리해
  두 기능이 서로의 히스토리 길이에 얽히지 않게 한다.
- GET은 저장분 읽기, 갱신은 cache_service TTL 게이트로 lazy — 주말·휴장에 매 요청 재fetch 안 함.
- 실패는 **degraded로 드러낸다**(조용한 fallback 금지): 얻은 것만 저장하고 못 얻은 지수를 이름으로 보고.
"""
from datetime import datetime, timezone
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
        price = closes[-1]
        prev = closes[-2] if len(closes) >= 2 else None
        change_pct = round((price / prev - 1) * 100, 2) if prev else None
        items.append({
            **base,
            "price": price, "change_pct": change_pct,
            "spark": _downsample(closes),
            "as_of": rows[-1]["snapshot_date"],
            "fetched_at": fetched_at,
        })
    conn.close()

    # 뒤처진 지수 = 다른 지수는 갱신됐는데 이것만 옛 수집 시각 → 그 지수만 실패했다는 뜻.
    # 프로세스 상태가 아니라 저장된 데이터에서 파생하므로 서버 재시작에도 살아남는다.
    stamps = [it["fetched_at"] for it in items if it.get("fetched_at")]
    newest = max(stamps) if stamps else None
    for it in items:
        it["lagging"] = bool(newest and it.get("fetched_at")
                             and _hours_apart(it["fetched_at"], newest) > LAG_HOURS)

    dates = [it["as_of"] for it in items if it["as_of"]]
    degraded = missing + [it["label"] for it in items if it["lagging"]]
    return {"as_of": max(dates) if dates else None, "items": items, "missing": missing,
            "degraded": degraded,
            "any_open": any(s["is_open"] for s in status.values()),
            "holiday_aware": False}   # 공휴일 캘린더 없음 — UI에 그대로 노출
