"""종목 하나에 카탈로그 전략을 전부 돌리는 기술적 분석 스캔 (docs/specs/market-strategies.md §기술적 분석 스캔, D-190).

기업 페이지 차트의 '기술적 분석' 버튼. 일봉 카탈로그(순위·10분봉 제외)를 그 종목의 저장 시세에 적용해
- 최근 N거래일 안에 켜진 사건 신호(돌파·교차·반전·재돌파…),
- 기준일의 상태(정배열·저점 높이기·신고가 근접…),
- 자료 부족으로 평가하지 못한 조건
을 나눈다. 모델 호출 없음, 종목당 수 ms. 국내는 stock_prices, 미국은 us_prices.
"""
from __future__ import annotations

import sqlite3

from pipeline.market_analysis.strategies import catalog, evaluate_strategy

# 기준일의 '상태'로 읽는 조건. 나머지는 발생일이 의미 있는 '사건'이라 최근 N거래일을 본다.
STATE_IDS = frozenset({"sma_bullish_order", "sma_bearish_order", "higher_lows", "lower_highs", "near_high_10d", "price_flat"})
# 신호를 읽는 순서: 구조 → 돌파/신고가 → 추세 전환 → 모멘텀 → 거래량/기타.
CATEGORY_ORDER = {"가격 구조": 0, "시세동향": 1, "지표신호": 2}
ROWS = 420


def load_rows(conn: sqlite3.Connection, code: str, market: str = "kr", limit: int = ROWS) -> list[dict]:
    table = "us_prices" if market == "us" else "stock_prices"
    shares = ", shares" if market == "kr" else ""
    rows = conn.execute(f"SELECT trade_date, open, high, low, close, volume{shares} FROM {table} WHERE stock_code=? "
                        "ORDER BY trade_date DESC LIMIT ?", (code, limit)).fetchall()[::-1]
    return [{"date": r["trade_date"], "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
             "volume": r["volume"], "shares": r["shares"] if market == "kr" else None} for r in rows]


def scannable() -> list[dict]:
    return [item for item in catalog() if item["timeframe"] == "1d" and item["available"] and not item["id"].startswith("rank_")]


def scan_rows(rows: list[dict], *, within: int = 5) -> dict:
    """순수 계산. rows는 날짜 오름차순 일봉."""
    if not rows:
        return {"as_of": None, "within": within, "signals": [], "states": [], "unavailable": [], "counts": {"evaluated": 0, "passed": 0, "failed": 0, "unavailable": 0}}
    signals, states, unavailable = [], [], []
    counts = {"evaluated": 0, "passed": 0, "failed": 0, "unavailable": 0}
    for item in scannable():
        is_state = item["id"] in STATE_IDS
        condition = {"strategy_id": item["id"], "params": dict(item["defaults"]), "within_days": 1 if is_state else within}
        result = evaluate_strategy(rows, condition)
        counts["evaluated"] += 1
        entry = {"id": item["id"], "label": item["label"], "category": item["category"], "status": result["status"],
                 "date": result.get("date"), "value": result.get("value"), "reference": result.get("reference"),
                 "reason": result.get("reason"), "evidence": result.get("evidence"), "within_days": condition["within_days"]}
        if result["status"] == "unavailable":
            counts["unavailable"] += 1
            unavailable.append(entry)
        elif is_state:
            counts["passed" if result["status"] == "pass" else "failed"] += 1
            states.append(entry)
        elif result["status"] == "pass":
            counts["passed"] += 1
            signals.append(entry)
        else:
            counts["failed"] += 1
    signals.sort(key=lambda e: (e["date"] or ""), reverse=True)
    signals.sort(key=lambda e: CATEGORY_ORDER.get(e["category"], 9))
    states.sort(key=lambda e: (e["status"] != "pass", CATEGORY_ORDER.get(e["category"], 9)))
    return {"as_of": rows[-1]["date"], "within": within, "signals": signals, "states": states,
            "unavailable": unavailable, "counts": counts, "sessions": len(rows)}


def chart_overlays(scan: dict) -> dict:
    """차트에 얹을 마커·선. 구조 조건의 evidence(피벗·선·채널)와 신호 발생일."""
    markers, lines = [], []
    seen = set()
    for entry in scan["signals"]:
        if entry["date"] and (entry["date"], entry["label"]) not in seen:
            seen.add((entry["date"], entry["label"]))
            markers.append({"time": entry["date"], "label": entry["label"], "kind": "signal"})
        evidence = entry.get("evidence") or {}
        for point in evidence.get("pivots", []):
            key = (point.get("date"), "스윙")
            if point.get("date") and key not in seen:
                seen.add(key)
                markers.append({"time": point["date"], "label": "스윙", "kind": "pivot", "price": point.get("price")})
        if evidence.get("line"):
            lines.append({"id": entry["id"], "label": entry["label"], "points": [{"time": p["date"], "value": p["price"]} for p in evidence["line"]]})
        channel = evidence.get("channel") or {}
        for side, name in (("upper", "상단"), ("lower", "하단")):
            if channel.get(side):
                lines.append({"id": f"{entry['id']}:{side}", "label": f"{entry['label']} {name}", "points": [{"time": p["date"], "value": p["price"]} for p in channel[side]]})
    for entry in scan["states"]:
        if entry["status"] != "pass":
            continue
        for point in (entry.get("evidence") or {}).get("pivots", []):
            key = (point.get("date"), "스윙")
            if point.get("date") and key not in seen:
                seen.add(key)
                markers.append({"time": point["date"], "label": "스윙", "kind": "pivot", "price": point.get("price")})
    markers.sort(key=lambda m: m["time"])
    return {"markers": markers, "lines": lines}


def scan_company(conn: sqlite3.Connection, code: str, market: str = "kr", within: int = 5) -> dict:
    rows = load_rows(conn, code, market)
    result = scan_rows(rows, within=within)
    return {"code": code, "market": market, **result, **chart_overlays(result)}
