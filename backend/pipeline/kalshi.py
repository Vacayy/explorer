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
"""


def _get(category: str, n: int) -> list[dict]:
    q = urllib.parse.urlencode({"order_by": "trending", "page_size": n * 2, "category": category})
    req = urllib.request.Request(f"{SEARCH}?{q}", headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    page = data.get("current_page")
    if not isinstance(page, list):
        raise ValueError("응답에 current_page가 없음 — Kalshi 검색 응답 모양이 바뀌었을 수 있음")
    return page


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
    outs = []
    for m in markets:
        price = _cents(m, "last_price")
        if price is None:
            continue
        outs.append({"label": str(m.get("yes_subtitle") or m.get("title") or m.get("ticker"))[:60], "price": price,
                     "prev": _cents(m, "previous_price"), "volume": m.get("volume")})
    if not outs:
        return None
    if len(outs) >= 3 and sum(o["price"] for o in outs) > 120:
        # 'Above X' 사다리(누적 기준선) — 확률 순이면 99% 칸만 남는다. 50%에 가까운 기준선이 시장의 중심 예상
        outs = sorted(outs, key=lambda o: abs(o["price"] - 50))[:TOP_OUTCOMES]
    outs.sort(key=lambda o: -o["price"])
    closes = sorted(m["close_ts"] for m in markets if m.get("close_ts"))
    return {"category": x.get("category") or "", "series_ticker": x.get("series_ticker") or "",
            "event_ticker": x["event_ticker"], "title": str(x.get("event_title") or x.get("series_title") or "")[:160],
            "subtitle": (str(x["event_subtitle"])[:80] if x.get("event_subtitle") else None),
            "recent_volume": int(x.get("recent_volume") or 0), "total_volume": int(x.get("total_volume") or 0) or None,
            "close_ts": closes[0] if closes else None, "outcomes": outs[:TOP_OUTCOMES]}


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


def collect(fetch=None) -> dict:
    """한 번 수집해 쌓는다. fetch는 테스트 대역(category, n) → 검색 결과 목록. 반환 {status, events, degraded}."""
    fetch = fetch or _get
    by_cat: dict[str, list[dict]] = {}
    degraded = []
    for cat, _, n in CATEGORIES:
        try:
            by_cat[cat] = [e for e in (parse_event(x) for x in fetch(cat, n)) if e]
        except Exception as e:  # noqa: BLE001 — 카테고리 하나가 실패해도 나머지는 쌓는다
            degraded.append(f"{cat}: {type(e).__name__}: {str(e)[:80]}")
    rows = pick(by_cat)
    if not rows:
        return {"status": "error", "events": 0, "degraded": degraded or ["결과 없음"]}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO kalshi_events (fetched_at, rank, category, series_ticker, event_ticker, title, subtitle, recent_volume, "
            "total_volume, close_ts, outcomes_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(now, i, e["category"], e["series_ticker"], e["event_ticker"], e["title"], e["subtitle"], e["recent_volume"],
              e["total_volume"], e["close_ts"], json.dumps(e["outcomes"], ensure_ascii=False)) for i, e in enumerate(rows)])
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "events": len(rows), "degraded": degraded}


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
        items = []
        for r in conn.execute("SELECT * FROM kalshi_events WHERE fetched_at=? ORDER BY rank", (at,)):
            items.append({"event_ticker": r["event_ticker"], "series_ticker": r["series_ticker"], "category": r["category"],
                          "category_label": CATEGORY_KO.get(r["category"], r["category"]), "title": r["title"],
                          "subtitle": r["subtitle"], "recent_volume": r["recent_volume"], "close_ts": r["close_ts"],
                          "url": f"https://kalshi.com/markets/{r['series_ticker'].lower()}",
                          "outcomes": [{**o, "change": (round(o["price"] - base[(r["event_ticker"], o["label"])], 1)
                                                       if (r["event_ticker"], o["label"]) in base else None)}
                                       for o in json.loads(r["outcomes_json"])]})
        return {"fetched_at": at, "base_at": base_at, "items": items}
    finally:
        conn.close()
