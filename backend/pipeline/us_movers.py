"""전일 미국시장 거래대금(=종가×거래량) 상위 종목 — TradingView 스크리너(무키) 일별 스냅샷.

전 미국 거래소(NYSE·Nasdaq·AMEX·CBOE…) 통합, ADR 포함(type='dr')·ETF 제외(type='fund').
sector·industry·전일 등락률까지 같은 1콜로 받아 브리핑 클러스터링을 LLM 0으로 지탱(us_briefing.py).
'팔로우 티커만'(us_data.py)의 예외 — 전체 시장 스크리닝(배경: DECISIONS D-094·D-095).

비공식 엔드포인트라 스키마가 바뀔 수 있다. 구조가 어긋나면 MoversSchemaError로 감지하고,
라우터는 마지막 성공 스냅샷을 status='stale'로 서빙해 프론트가 경고를 띄운다.
"""
import json
import urllib.error
import urllib.request
from datetime import date, datetime

from database import get_connection
from services import cache_service

CACHE_KEY = "us_movers_dollar_vol"
TTL_SECONDS = 86400          # 24h — 아침 브리핑용 하루 1회 갱신(마감 후 크론/수동 버튼이 force로 새로고침)
LIMIT = 20                    # 상위 N 종목
FETCH_ROWS = 60              # ETF 제외 후 20개 확보용 여유
RETAIN_DAYS = 7              # 스냅샷 보존 일수(신규 진입 판정용)
SOURCE = "tradingview-scanner"
TV_URL = "https://scanner.tradingview.com/america/scan"
# 응답 각 행 d[]의 컬럼 순서 — 스키마 검증 기준(순서·개수가 곧 계약)
COLUMNS = ["name", "description", "close", "volume", "Value.Traded",
           "change", "sector", "industry", "exchange", "type", "market_cap_basic"]


class MoversSchemaError(Exception):
    """TradingView 응답 구조가 기대와 다름 — 스키마 변경·차단·네트워크 실패 감지."""


def _session_date() -> str:
    """스냅샷 세션 날짜 = US/Eastern 기준 오늘(직전 완료 세션 근사). tz 미가용 시 로컬."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:
        return date.today().isoformat()


def _fetch_raw() -> list[dict]:
    """TradingView 스크리너 호출 → 검증된 행 리스트. 구조가 어긋나면 MoversSchemaError."""
    body = json.dumps({
        "columns": COLUMNS,
        "sort": {"sortBy": "Value.Traded", "sortOrder": "desc"},
        "range": [0, FETCH_ROWS],
    }).encode()
    req = urllib.request.Request(TV_URL, data=body, headers={
        "Content-Type": "text/plain;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (stock-explorer)",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        raise MoversSchemaError(f"TradingView 요청 실패: {e}") from e

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        raise MoversSchemaError("응답에 data 배열이 없음 (스키마 변경 의심)")

    rows: list[dict] = []
    for r in data:
        d = r.get("d") if isinstance(r, dict) else None
        if not isinstance(d, list) or len(d) != len(COLUMNS):
            got = len(d) if isinstance(d, list) else "N/A"
            raise MoversSchemaError(f"행 컬럼 수 불일치 (기대 {len(COLUMNS)}, 실제 {got})")
        name, desc, close, volume, value, change, sector, industry, exchange, typ, mcap = d
        if not isinstance(name, str) or not isinstance(value, (int, float)):
            raise MoversSchemaError("필드 타입 불일치 (ticker/거래대금)")
        rows.append({
            "ticker": name, "name": desc or name, "close": close, "volume": volume,
            "dollar_volume": value, "change_pct": change, "sector": sector, "industry": industry,
            "exchange": exchange, "type": typ, "market_cap": mcap,
        })
    return rows


def _prior_tickers(conn, trade_date: str) -> set[str]:
    """직전(오늘 아닌 가장 최근) 스냅샷의 티커 집합 — 신규 진입 판정 기준."""
    row = conn.execute(
        "SELECT max(trade_date) d FROM us_movers WHERE trade_date < ?", (trade_date,)).fetchone()
    if not row or not row["d"]:
        return set()
    return {r["ticker"] for r in conn.execute(
        "SELECT ticker FROM us_movers WHERE trade_date=?", (row["d"],)).fetchall()}


def _read_snapshot(conn, trade_date: str | None = None) -> list[dict]:
    if trade_date is None:
        row = conn.execute("SELECT max(trade_date) d FROM us_movers").fetchone()
        trade_date = row["d"] if row else None
    if not trade_date:
        return []
    rows = conn.execute(
        "SELECT trade_date, rank, ticker, name, close, volume, dollar_volume, change_pct, "
        "sector, industry, exchange, market_cap, is_adr, is_new, fetched_at "
        "FROM us_movers WHERE trade_date=? ORDER BY rank", (trade_date,)).fetchall()
    return [dict(r) for r in rows]


def _store(leaders: list[dict], trade_date: str) -> None:
    conn = get_connection()
    prior = _prior_tickers(conn, trade_date)
    conn.execute("DELETE FROM us_movers WHERE trade_date=?", (trade_date,))  # 당일 재적재 멱등
    for i, r in enumerate(leaders, start=1):
        conn.execute(
            "INSERT INTO us_movers (trade_date, rank, ticker, name, close, volume, dollar_volume, "
            "change_pct, sector, industry, exchange, market_cap, is_adr, is_new, fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'))",
            (trade_date, i, r["ticker"], r["name"], r["close"], r["volume"], r["dollar_volume"],
             r["change_pct"], r["sector"], r["industry"], r["exchange"], r["market_cap"],
             1 if r["type"] == "dr" else 0, 0 if r["ticker"] in prior or not prior else 1))
    # 보존 초과분 정리
    old = conn.execute(
        "SELECT DISTINCT trade_date FROM us_movers ORDER BY trade_date DESC LIMIT -1 OFFSET ?",
        (RETAIN_DAYS,)).fetchall()
    for o in old:
        conn.execute("DELETE FROM us_movers WHERE trade_date=?", (o["trade_date"],))
    conn.commit()
    conn.close()


def _result(status: str, items: list[dict], error: str | None) -> dict:
    return {"status": status, "items": items, "source": SOURCE,
            "trade_date": items[0]["trade_date"] if items else None,
            "fetched_at": items[0]["fetched_at"] if items else None, "error": error}


def read_leaders() -> dict:
    """최신 스냅샷 순수 읽기 — 네트워크 없음(일반 로드용). 갱신은 버튼=get_leaders(force=True) (D-100)."""
    conn = get_connection()
    items = _read_snapshot(conn)
    conn.close()
    return _result("ok", items, None)


def get_leaders(force: bool = False) -> dict:
    """거래대금 상위 종목 — 캐시 우선. 반환 {status, items, source, trade_date, fetched_at, error}.

    status: ok(신선/막 갱신) · stale(갱신 실패 → 마지막 성공 스냅샷) · error(데이터 없음).
    items 각 행에 sector·industry·change_pct·is_new 포함(브리핑 클러스터링 재료).
    """
    conn = get_connection()
    if not force and cache_service.is_cached(CACHE_KEY):
        cached = _read_snapshot(conn)
        conn.close()
        if cached:
            return _result("ok", cached, None)
    else:
        conn.close()

    try:
        raw = _fetch_raw()
    except MoversSchemaError as e:
        conn = get_connection(); last = _read_snapshot(conn); conn.close()
        return _result("stale", last, str(e)) if last else _result("error", [], str(e))

    leaders = [r for r in raw if r.get("type") != "fund"][:LIMIT]  # ADR 유지, ETF 제외
    if not leaders:
        conn = get_connection(); last = _read_snapshot(conn); conn.close()
        msg = "필터 후 종목 0 (스키마 변경 의심)"
        return _result("stale", last, msg) if last else _result("error", [], msg)

    trade_date = _session_date()
    _store(leaders, trade_date)
    cache_service.set_cache(CACHE_KEY, TTL_SECONDS)
    conn = get_connection(); items = _read_snapshot(conn, trade_date); conn.close()
    return _result("ok", items, None)
