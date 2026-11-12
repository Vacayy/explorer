"""Kalshi 예측시장 — 금융·경제·테크·정치 카테고리의 인기 이벤트 확률 (홈 › 대시보드 캐러셀, 2026-11-12).

원천: Kalshi 웹사이트가 쓰는 검색 주소 `GET https://api.elections.kalshi.com/v1/search/series?order_by=trending&category=…`
(로그인·키 없음). 공식 trade-api v2에는 인기순·카테고리 필터가 없어 열린 시장 전체(120일 안 마감만 4만 건+, 2분)를
훑어야 해서 이 주소를 쓴다 — 공식 문서에 없는 주소라 응답 모양이 바뀌면 수집이 error로 남는다(조용히 다른 원천으로 넘어가지 않는다).

카테고리마다 인기순 상위를 받아(금융·경제에 칸을 더 준다) 이벤트당 확률 상위 결과 3개를 저장한다. 실행마다 새 행을 쌓는다(덮어쓰지 않음 —
나중에 확률 추이를 볼 수 있게). 외부 요청 4건/회, LLM 0.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from database import get_connection

SEARCH = "https://api.elections.kalshi.com/v1/search/series"
# (Kalshi 카테고리, 화면 이름, 받을 수) — 금융·경제 가중(사용자 요청)
CATEGORIES = [("Financials", "금융", 6), ("Economics", "경제", 6),
              ("Science and Technology", "테크", 3), ("Politics", "정치", 3)]
# 캐러셀 순서 — 금융·경제가 앞쪽과 자주 오게 섞는다
PATTERN = ["Financials", "Economics", "Science and Technology", "Financials", "Economics", "Politics"]
MIN_VOLUME = 1000        # 최근 거래량(계약 수)이 이보다 적으면 뺀다 — 인기순에도 거의 거래 없는 것이 섞인다
SKIP_FREQ = {"daily", "hourly"}   # '내일 경유 가격' 같은 하루짜리 시리즈는 캐러셀에 안 맞는다
CHANGE_AFTER_H = 20      # 변화 = 이 시간 이상 지난 마지막 수집분 대비(같은 이벤트·같은 결과)
TOP_OUTCOMES = 3
UA = "explorer/1.0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS kalshi_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at    TEXT NOT NULL,          -- 수집 시각 UTC ISO — 같은 실행의 행은 같은 값
    rank          INTEGER NOT NULL,       -- 캐러셀 순서(0부터)
    category      TEXT NOT NULL,          -- Kalshi 카테고리(Financials·Economics·Science and Technology·Politics)
    series_ticker TEXT NOT NULL,
    event_ticker  TEXT NOT NULL,
    title         TEXT NOT NULL,
    subtitle      TEXT,
    recent_volume INTEGER,                -- Kalshi '최근 거래량'(계약 수)
    total_volume  INTEGER,
    close_ts      TEXT,                   -- 가장 이른 결과 마감 시각 UTC
    outcomes_json TEXT NOT NULL           -- [{label, price(0~100), prev(0~100|null), volume}] 확률 상위 TOP_OUTCOMES
);
CREATE INDEX IF NOT EXISTS idx_kalshi_events_fetched ON kalshi_events(fetched_at);
-- 추적(카드 오른쪽 위 핀) — 인기순에서 빠져도 수집마다 이 이벤트를 따로 받아 캐러셀 맨 앞에 둔다
CREATE TABLE IF NOT EXISTS kalshi_pins (
    event_ticker  TEXT PRIMARY KEY,
    series_ticker TEXT NOT NULL,
    pinned_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
-- 결과(마켓)별 일봉 확률 — 카드 추이선·상세 차트. 같은 날은 덮어쓴다(늦은 수집이 고침)
CREATE TABLE IF NOT EXISTS kalshi_candles (
    market_ticker TEXT NOT NULL,
    day           TEXT NOT NULL,          -- UTC 날짜(봉 끝 시각 기준)
    price         REAL NOT NULL,          -- 0~100, 체결 없으면 직전 가격
    PRIMARY KEY (market_ticker, day)
);
-- 상세 창 원본(Kalshi trade-api v2 이벤트) — cache_service TTL과 함께 쓴다
CREATE TABLE IF NOT EXISTS kalshi_event_cache (
    event_ticker TEXT PRIMARY KEY,
    body_json    TEXT NOT NULL,
    fetched_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

V2 = "https://api.elections.kalshi.com/trade-api/v2"
SPARK_DAYS = 60
DETAIL_TTL = 600          # 상세 이벤트 10분
CANDLE_TTL = 1800         # 상세 차트 봉 30분
DETAIL_LINES = 4          # 상세 차트에 그리는 결과 수
RANGE_DAYS = {"1m": 31, "3m": 92, "1y": 366}


def _get(category: str, n: int) -> list[dict]:
    q = urllib.parse.urlencode({"order_by": "trending", "page_size": n * 2, "category": category})
    req = urllib.request.Request(f"{SEARCH}?{q}", headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    page = data.get("current_page")
    if not isinstance(page, list):
        raise ValueError("응답에 current_page가 없음 — Kalshi 검색 응답 모양이 바뀌었을 수 있음")
    return page


def _v2(path: str) -> dict:
    req = urllib.request.Request(f"{V2}{path}", headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_event(event_ticker: str) -> dict:
    """공식 trade-api v2 이벤트(결과 전부·규칙 포함)."""
    d = _v2(f"/events/{urllib.parse.quote(event_ticker)}?with_nested_markets=true")
    ev = d.get("event") or {}
    if not ev.get("event_ticker"):
        raise ValueError("이벤트 응답에 event_ticker가 없음")
    ev["markets"] = ev.get("markets") or d.get("markets") or []
    return ev


def fetch_candles(series: str, market: str, days: int) -> list[tuple[str, float]]:
    """일봉 확률 [(UTC 날짜, 0~100)] — 체결 없는 날은 직전 가격."""
    now = int(datetime.now(timezone.utc).timestamp())
    d = _v2(f"/series/{urllib.parse.quote(series)}/markets/{urllib.parse.quote(market)}/candlesticks"
            f"?start_ts={now - days * 86400}&end_ts={now}&period_interval=1440")
    out = []
    for c in d.get("candlesticks") or []:
        p = c.get("price") or {}
        v = p.get("close_dollars") or p.get("previous_dollars")
        if v in (None, "") or not c.get("end_period_ts"):
            continue
        day = datetime.fromtimestamp(int(c["end_period_ts"]) - 1, timezone.utc).date().isoformat()
        out.append((day, round(float(v) * 100, 1)))
    return out


def _cents(m: dict, key: str) -> float | None:
    v = m.get(f"{key}_dollars")
    if v not in (None, ""):
        return round(float(v) * 100, 1)
    v = m.get(key)
    return float(v) if isinstance(v, (int, float)) else None


def parse_event(x: dict) -> dict | None:
    """검색 결과 한 건 → 저장 모양. 결과(마켓)가 없거나 거래가 적으면 None."""
    markets = [m for m in (x.get("markets") or []) if isinstance(m, dict) and not m.get("result")]
    if not markets or (x.get("recent_volume") or 0) < MIN_VOLUME or not x.get("event_ticker"):
        return None
    if ((x.get("product_metadata") or {}).get("series_frequency") or "") in SKIP_FREQ:
        return None
    outs = [{"label": str(m.get("yes_subtitle") or m.get("title") or m.get("ticker"))[:60], "ticker": m.get("ticker"),
             "price": _cents(m, "last_price"), "prev": _cents(m, "previous_price"), "volume": m.get("volume")} for m in markets]
    outs = shape([o for o in outs if o["price"] is not None])
    if not outs:
        return None
    closes = sorted(m["close_ts"] for m in markets if m.get("close_ts"))
    return {"category": x.get("category") or "", "series_ticker": x.get("series_ticker") or "",
            "event_ticker": x["event_ticker"], "title": str(x.get("event_title") or x.get("series_title") or "")[:160],
            "subtitle": (str(x["event_subtitle"])[:80] if x.get("event_subtitle") else None),
            "recent_volume": int(x.get("recent_volume") or 0), "total_volume": int(x.get("total_volume") or 0) or None,
            "close_ts": closes[0] if closes else None, "outcomes": outs}


def shape(outs: list[dict], n: int = TOP_OUTCOMES) -> list[dict]:
    """보일 결과 n개 — 확률 순. 'Above X' 사다리(누적 기준선, 합 > 120)는 99% 칸만 남기 쉬워 50%에 가까운 기준선을 고른다."""
    if len(outs) >= 3 and sum(o["price"] for o in outs) > 120:
        outs = sorted(outs, key=lambda o: abs(o["price"] - 50))[:n]
    return sorted(outs, key=lambda o: -o["price"])[:n]


def parse_v2_event(ev: dict) -> dict | None:
    """trade-api v2 이벤트 → 저장 모양(추적 이벤트용 — 거래량·주기 필터 없음). 마감된 결과도 남긴다."""
    markets = [m for m in ev.get("markets") or [] if isinstance(m, dict)]
    outs = [{"label": str(m.get("yes_sub_title") or m.get("title") or m.get("ticker"))[:60], "ticker": m.get("ticker"),
             "price": _cents(m, "last_price"), "prev": _cents(m, "previous_price"),
             "volume": int(float(m.get("volume_fp") or 0)) or None} for m in markets]
    outs = shape([o for o in outs if o["price"] is not None])
    if not outs:
        return None
    closes = sorted(m["close_time"] for m in markets if m.get("close_time"))
    return {"category": ev.get("category") or "", "series_ticker": ev.get("series_ticker") or "",
            "event_ticker": ev["event_ticker"], "title": str(ev.get("title") or "")[:160],
            "subtitle": (str(ev["sub_title"])[:80] if ev.get("sub_title") else None),
            "recent_volume": int(sum(float(m.get("volume_24h_fp") or 0) for m in markets)),
            "total_volume": int(sum(float(m.get("volume_fp") or 0) for m in markets)) or None,
            "close_ts": closes[0] if closes else None, "outcomes": outs}


def pick(by_cat: dict[str, list[dict]]) -> list[dict]:
    """카테고리별 상위(받을 수만큼, 이벤트 중복 제거)를 PATTERN 순서로 섞는다. 한 카테고리가 바닥나면 남은 것을 이어 붙인다."""
    seen: set[str] = set()
    queues: dict[str, list[dict]] = {}
    for cat, _, n in CATEGORIES:
        q = []
        for e in by_cat.get(cat, []):
            if e["event_ticker"] in seen:
                continue
            seen.add(e["event_ticker"])
            q.append(e)
            if len(q) >= n:
                break
        queues[cat] = q
    out: list[dict] = []
    while any(queues.values()):
        for cat in PATTERN:
            if queues.get(cat):
                out.append(queues[cat].pop(0))
    return out


def collect(fetch=None, event=None, candles=None) -> dict:
    """한 번 수집해 쌓는다 — 인기순(카테고리 가중) + 추적 이벤트(맨 앞), 이벤트마다 대표 결과의 일봉.
    fetch·event·candles는 테스트 대역. 반환 {status, events, pinned, degraded}."""
    fetch, event, candles = fetch or _get, event or fetch_event, candles or fetch_candles
    by_cat: dict[str, list[dict]] = {}
    degraded = []
    for cat, _, n in CATEGORIES:
        try:
            by_cat[cat] = [e for e in (parse_event(x) for x in fetch(cat, n)) if e]
        except Exception as e:  # noqa: BLE001 — 카테고리 하나가 실패해도 나머지는 쌓는다
            degraded.append(f"{cat}: {type(e).__name__}: {str(e)[:80]}")
    rows = pick(by_cat)
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        pins = conn.execute("SELECT event_ticker FROM kalshi_pins ORDER BY pinned_at").fetchall()
    finally:
        conn.close()
    trending = {e["event_ticker"]: e for e in rows}
    pinned = []
    for p in pins:
        t = p["event_ticker"]
        if t in trending:
            pinned.append(trending.pop(t))
            continue
        try:
            e = parse_v2_event(event(t))
            if e:
                pinned.append(e)
        except Exception as ex:  # noqa: BLE001
            degraded.append(f"추적 {t}: {type(ex).__name__}: {str(ex)[:80]}")
    rows = pinned + [e for e in rows if e["event_ticker"] in trending]
    if not rows:
        return {"status": "error", "events": 0, "pinned": 0, "degraded": degraded or ["결과 없음"]}
    spark: list[tuple[str, str, float]] = []
    failed = 0
    for e in rows:
        top = e["outcomes"][0].get("ticker")
        if not top:
            continue
        try:
            spark += [(top, d, v) for d, v in candles(e["series_ticker"], top, SPARK_DAYS)]
        except Exception:  # noqa: BLE001 — 추이선은 부가 정보, 확률 저장은 막지 않는다
            failed += 1
    if failed:
        degraded.append(f"추이선 {failed}건 실패")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        conn.executemany("INSERT OR REPLACE INTO kalshi_candles (market_ticker, day, price) VALUES (?,?,?)", spark)
        conn.executemany(
            "INSERT INTO kalshi_events (fetched_at, rank, category, series_ticker, event_ticker, title, subtitle, recent_volume, "
            "total_volume, close_ts, outcomes_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(now, i, e["category"], e["series_ticker"], e["event_ticker"], e["title"], e["subtitle"], e["recent_volume"],
              e["total_volume"], e["close_ts"], json.dumps(e["outcomes"], ensure_ascii=False)) for i, e in enumerate(rows)])
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "events": len(rows), "pinned": len(pinned), "degraded": degraded}


CATEGORY_KO = {c: ko for c, ko, _ in CATEGORIES}


def latest() -> dict:
    """마지막 수집분(캐러셀 순서). 없으면 items 빈 목록. LLM·외부 호출 0."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT MAX(fetched_at) f FROM kalshi_events").fetchone()
        at = row["f"] if row else None
        if not at:
            return {"fetched_at": None, "base_at": None, "items": []}
        # 변화 기준 — CHANGE_AFTER_H 이상 지난 마지막 수집분(Kalshi previous_price는 거래가 없던 결과에서 0으로 와 쓰지 않는다)
        base_at = conn.execute("SELECT MAX(fetched_at) f FROM kalshi_events WHERE fetched_at <= datetime(?, ?)",
                               (at, f"-{CHANGE_AFTER_H} hours")).fetchone()["f"]
        base: dict[tuple[str, str], float] = {}
        if base_at:
            for b in conn.execute("SELECT event_ticker, outcomes_json FROM kalshi_events WHERE fetched_at=?", (base_at,)):
                for o in json.loads(b["outcomes_json"]):
                    base[(b["event_ticker"], o["label"])] = o["price"]
        pins = {r["event_ticker"] for r in conn.execute("SELECT event_ticker FROM kalshi_pins")}
        rows = conn.execute("SELECT * FROM kalshi_events WHERE fetched_at=? ORDER BY rank", (at,)).fetchall()
        # 마지막 수집 뒤에 추적을 켰고 그 묶음에 없는 이벤트 — 가장 최근 행을 앞에 붙인다(다음 수집부터는 따로 받는다)
        have = {r["event_ticker"] for r in rows}
        extra = [conn.execute("SELECT * FROM kalshi_events WHERE event_ticker=? ORDER BY fetched_at DESC LIMIT 1", (t,)).fetchone()
                 for t in pins - have]
        rows = [r for r in extra if r] + list(rows)
        items = []
        for r in rows:
            outs = json.loads(r["outcomes_json"])
            top = outs[0].get("ticker") if outs else None
            spark = [[d, v] for d, v in conn.execute(
                "SELECT day, price FROM kalshi_candles WHERE market_ticker=? ORDER BY day DESC LIMIT ?", (top, SPARK_DAYS))][::-1] if top else []
            items.append({"event_ticker": r["event_ticker"], "series_ticker": r["series_ticker"], "category": r["category"],
                          "pinned": r["event_ticker"] in pins, "spark": spark,
                          "category_label": CATEGORY_KO.get(r["category"], r["category"]), "title": r["title"],
                          "subtitle": r["subtitle"], "recent_volume": r["recent_volume"], "close_ts": r["close_ts"],
                          "url": f"https://kalshi.com/markets/{r['series_ticker'].lower()}",
                          "outcomes": [{**o, "change": (round(o["price"] - base[(r["event_ticker"], o["label"])], 1)
                                                       if (r["event_ticker"], o["label"]) in base else None)}
                                       for o in outs]})
        items.sort(key=lambda x: not x["pinned"])       # 추적 이벤트 맨 앞(나머지 순서 유지)
        return {"fetched_at": at, "base_at": base_at, "items": items}
    finally:
        conn.close()


def _strike(o: dict) -> tuple:
    """기준선별 결과 정렬 키 — 라벨의 첫 숫자('Above 3.4%' → 3.4), 없으면 라벨."""
    import re
    m = re.search(r"-?\d[\d,]*\.?\d*", o["label"])
    try:
        return (0, float(m.group().replace(",", ""))) if m else (1, o["label"])
    except ValueError:
        return (1, o["label"])


def set_pin(event_ticker: str, series_ticker: str, on: bool) -> bool:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        if on:
            conn.execute("INSERT OR IGNORE INTO kalshi_pins (event_ticker, series_ticker) VALUES (?,?)", (event_ticker, series_ticker))
        else:
            conn.execute("DELETE FROM kalshi_pins WHERE event_ticker=?", (event_ticker,))
        conn.commit()
        return on
    finally:
        conn.close()


def detail(event_ticker: str, range_: str = "3m", event=None, candles=None) -> dict:
    """상세 창 — 결과 전부(확률·24시간 거래·상태)·규칙·결과별 일봉(상위 DETAIL_LINES개). 외부 호출은 cache_service TTL 안에서 한 번."""
    from services.cache_service import is_cached, set_cache
    event, candles = event or fetch_event, candles or fetch_candles
    days = RANGE_DAYS.get(range_, 92)
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        key = f"kalshi:event:{event_ticker}"
        row = conn.execute("SELECT body_json, fetched_at FROM kalshi_event_cache WHERE event_ticker=?", (event_ticker,)).fetchone()
        if row and is_cached(key):
            ev, fetched = json.loads(row["body_json"]), row["fetched_at"]
        else:
            ev = event(event_ticker)
            conn.execute("INSERT OR REPLACE INTO kalshi_event_cache (event_ticker, body_json, fetched_at) VALUES (?,?,datetime('now'))",
                         (event_ticker, json.dumps(ev, ensure_ascii=False)))
            conn.commit()
            set_cache(key, DETAIL_TTL)
            fetched = conn.execute("SELECT fetched_at FROM kalshi_event_cache WHERE event_ticker=?", (event_ticker,)).fetchone()[0]
        markets = [m for m in ev.get("markets") or [] if isinstance(m, dict)]
        outs = [{"label": str(m.get("yes_sub_title") or m.get("title") or m.get("ticker"))[:80], "ticker": m.get("ticker"),
                 "price": _cents(m, "last_price"), "volume_24h": int(float(m.get("volume_24h_fp") or 0)),
                 "volume": int(float(m.get("volume_fp") or 0)), "status": m.get("status") or "",
                 "result": m.get("result") or None, "close_ts": m.get("close_time")} for m in markets]
        outs = [o for o in outs if o["price"] is not None]
        lines = [o for o in shape([dict(o) for o in outs], DETAIL_LINES)]
        series = []
        for o in lines:
            ckey = f"kalshi:candles:{o['ticker']}:{range_}"
            if not is_cached(ckey):
                conn.executemany("INSERT OR REPLACE INTO kalshi_candles (market_ticker, day, price) VALUES (?,?,?)",
                                 [(o["ticker"], d, v) for d, v in candles(ev.get("series_ticker") or "", o["ticker"], days)])
                conn.commit()
                set_cache(ckey, CANDLE_TTL)
            pts = [[d, v] for d, v in conn.execute(
                "SELECT day, price FROM kalshi_candles WHERE market_ticker=? AND day >= date('now', ?) ORDER BY day",
                (o["ticker"], f"-{days} days"))]
            series.append({"ticker": o["ticker"], "label": o["label"], "points": pts})
        top = next((m for m in markets if m.get("ticker") == (lines[0]["ticker"] if lines else None)), markets[0] if markets else {})
        pinned = conn.execute("SELECT 1 FROM kalshi_pins WHERE event_ticker=?", (event_ticker,)).fetchone() is not None
        closes = sorted(m["close_time"] for m in markets if m.get("close_time"))
        return {"event_ticker": event_ticker, "series_ticker": ev.get("series_ticker") or "", "category": ev.get("category") or "",
                "category_label": CATEGORY_KO.get(ev.get("category") or "", ev.get("category") or ""),
                "title": ev.get("title") or "", "subtitle": ev.get("sub_title") or None,
                "mutually_exclusive": bool(ev.get("mutually_exclusive")), "close_ts": closes[0] if closes else None,
                "rules": top.get("rules_primary") or None, "url": f"https://kalshi.com/markets/{(ev.get('series_ticker') or '').lower()}",
                "pinned": pinned, "fetched_at": fetched, "range": range_ if range_ in RANGE_DAYS else "3m",
                "outcomes": sorted(outs, key=lambda o: -o["price"]) if ev.get("mutually_exclusive") else sorted(outs, key=_strike),
                "series": series}
    finally:
        conn.close()
