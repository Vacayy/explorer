"""종목 하나의 차트에 채널·추세선을 그리는 결정적 계산 (docs/specs/chart-structure.md, D-195).

"올해 전고점들을 기반으로 큰 채널을 그려줘"를 조건 검색이 아니라 그리기 요청으로 받는다.
스윙 검출·직선 적합은 가격 구조 전략(D-187)의 규칙을 그대로 쓰고, 모델 호출은 없다.
"""
from __future__ import annotations

import math
import re
import sqlite3
from datetime import date, timedelta

from pipeline.market_analysis.strategies import _fit_line, _pivot_indexes
from pipeline.technical_scan import load_rows

KINDS = {"channel": "채널", "trendline_high": "고점 추세선", "trendline_low": "저점 추세선"}
FITS = ("two_point", "regression")
WINDOWS = ("ytd", "3m", "6m", "1y", "2y")
CONTEXT_BARS = 20
TOUCH_TOLERANCE = 0.005
MIN_SWING, MAX_SWING = 2, 30


class StructureUnavailable(ValueError):
    pass


def window_bounds(window: str, as_of: str) -> tuple[str, str]:
    """기간 문자열 → (from, to). 직접 날짜는 'YYYY-MM-DD:YYYY-MM-DD'."""
    end = date.fromisoformat(as_of)
    if ":" in window:
        start_text, end_text = window.split(":", 1)
        start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
        if start >= end:
            raise StructureUnavailable("기간의 시작이 끝보다 앞서야 합니다.")
        return start.isoformat(), end.isoformat()
    if window == "ytd":
        return date(end.year, 1, 1).isoformat(), end.isoformat()
    match = re.fullmatch(r"(\d{1,2})([my])", window)
    if not match:
        raise StructureUnavailable("지원하지 않는 기간입니다.")
    amount, unit = int(match.group(1)), match.group(2)
    days = amount * (30 if unit == "m" else 365)
    return (end - timedelta(days=days)).isoformat(), end.isoformat()


def _pivots(rows: list[dict], swing: int, key: str, low: bool) -> list[int]:
    return _pivot_indexes(rows, swing, key, low) if len(rows) > 2 * swing else []


def _two_point(rows: list[dict], indexes: list[int], key: str, highest: bool) -> list[int]:
    """P1 = 극값 스윙, P2 = P1 이후 같은 방향 두 번째 극값(없으면 이전). 손으로 긋는 '전고점 연결'과 같다."""
    pick = max if highest else min
    first = pick(indexes, key=lambda k: rows[k][key])
    after = [k for k in indexes if k > first]
    before = [k for k in indexes if k < first]
    second = pick(after, key=lambda k: rows[k][key]) if after else pick(before, key=lambda k: rows[k][key])
    return sorted((first, second))


def _channel_points(rows: list[dict], indexes: list[int], fit: str) -> tuple[list[int], list[int]]:
    """채널 상단은 가장 높은 고점 두 개(two_point) 또는 전체 스윙 고점의 회귀선."""
    if fit == "regression":
        return sorted(indexes), sorted(indexes)
    top_two = sorted(sorted(indexes, key=lambda k: rows[k]["high"], reverse=True)[:2])
    return top_two, top_two


def structure(rows: list[dict], kind: str, swing: int, fit: str = "two_point") -> dict:
    """기간 안 일봉(rows, 날짜 오름차순)에 구조를 그린다. 순수 계산."""
    if kind not in KINDS or fit not in FITS:
        raise StructureUnavailable("지원하지 않는 구조 또는 적합 방식입니다.")
    if not MIN_SWING <= swing <= MAX_SWING:
        raise StructureUnavailable("스윙 폭은 2~30 사이여야 합니다.")
    rows = [r for r in rows if all(isinstance(r.get(k), (int, float)) and math.isfinite(r[k]) and r[k] > 0 for k in ("open", "high", "low", "close"))]
    if len(rows) < 5:
        raise StructureUnavailable("기간 안에 유효한 시세가 5거래일 미만입니다.")
    key, low = ("low", True) if kind == "trendline_low" else ("high", False)
    used, indexes, notes = swing, [], []
    while used >= MIN_SWING:
        indexes = _pivots(rows, used, key, low)
        if len(indexes) >= 2:
            break
        used -= 1
    if len(indexes) < 2:
        raise StructureUnavailable("기간이 짧거나 변동이 작아 스윙 점을 2개 이상 찾지 못했습니다. 기간을 늘리거나 스윙 폭을 줄여 보세요.")
    if used != swing:
        notes.append(f"스윙 폭 {swing}에서 {KINDS[kind]}의 기준점이 2개 미만이어서 {used}로 줄여 그렸습니다.")

    last = len(rows) - 1
    if kind == "channel":
        anchors, fit_points = _channel_points(rows, indexes, fit)
    else:
        anchors = _two_point(rows, indexes, key, not low) if fit == "two_point" else sorted(indexes)
        fit_points = anchors
    a, b = _fit_line([(k, rows[k][key]) for k in fit_points])
    start = anchors[0]
    line_at = lambda i: a + b * i  # noqa: E731

    def segment(identifier: str, label: str, offset: float = 0.0) -> dict:
        return {"id": identifier, "label": label,
                "points": [{"time": rows[start]["date"], "value": round(line_at(start) + offset, 4)},
                           {"time": rows[last]["date"], "value": round(line_at(last) + offset, 4)}]}

    lines, summary = [], {}
    close = rows[last]["close"]
    if kind == "channel":
        offset = min(rows[i]["low"] - line_at(i) for i in range(start, last + 1))
        upper_now, lower_now = line_at(last), line_at(last) + offset
        lines = [segment("channel:upper", "채널 상단"), segment("channel:lower", "채널 하단", offset)]
        width = upper_now - lower_now
        summary = {"upper_now": round(upper_now, 4), "lower_now": round(lower_now, 4), "close": close,
                   "position_pct": round((close - lower_now) / width * 100, 1) if width > 0 else None,
                   "width_pct": round(width / lower_now * 100, 1) if lower_now > 0 else None,
                   "touches_upper": sum(1 for i in range(start, last + 1) if abs(rows[i]["high"] - line_at(i)) <= TOUCH_TOLERANCE * line_at(i)),
                   "touches_lower": sum(1 for i in range(start, last + 1) if abs(rows[i]["low"] - (line_at(i) + offset)) <= TOUCH_TOLERANCE * abs(line_at(i) + offset))}
    else:
        line_now = line_at(last)
        lines = [segment(kind, KINDS[kind])]
        summary = {"line_now": round(line_now, 4), "close": close,
                   "distance_pct": round((close - line_now) / line_now * 100, 2) if line_now > 0 else None,
                   "touches": sum(1 for i in range(start, last + 1) if abs(rows[i][key] - line_at(i)) <= TOUCH_TOLERANCE * abs(line_at(i)))}
    base = line_at(start)
    summary["slope_pct_per_session"] = round(b / base * 100, 3) if base else None
    summary["sessions"] = last - start + 1
    pivots = [{"time": rows[k]["date"], "price": rows[k][key], "side": "high" if not low else "low", "anchor": k in anchors} for k in indexes]
    return {"kind": kind, "fit": fit, "swing": used, "requested_swing": swing, "lines": lines, "pivots": pivots,
            "summary": summary, "notes": notes, "first": rows[start]["date"], "last": rows[last]["date"]}


def draw(conn: sqlite3.Connection, code: str, market: str, kind: str, window: str, swing: int, fit: str) -> dict:
    rows = load_rows(conn, code, market, limit=800)
    if not rows:
        raise LookupError("저장된 시세가 없는 종목입니다.")
    start, end = window_bounds(window, rows[-1]["date"])
    inside = [r for r in rows if start <= r["date"] <= end]
    if not inside:
        raise StructureUnavailable("요청한 기간에 시세가 없습니다.")
    first_index = rows.index(inside[0])
    context = rows[max(0, first_index - CONTEXT_BARS):first_index]
    result = structure(inside, kind, swing, fit)
    notes = list(result["notes"])
    if inside[0]["date"] > start and first_index == 0:
        notes.append(f"저장된 시세가 {inside[0]['date']}부터라 기간 앞부분이 잘렸습니다.")
    candles = [{"time": r["date"], "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"]} for r in context + inside]
    return {"code": code, "market": market, "window": {"from": inside[0]["date"], "to": inside[-1]["date"], "requested_from": start, "sessions": len(inside)},
            "candles": candles, **{**result, "notes": notes}}


# --- 질문 해석 (규칙) ------------------------------------------------------------------------

STRUCTURE_WORDS = re.compile(r"채널|추세선|고점.{0,4}(연결|선)|저점.{0,4}(연결|선)|전고점|전저점|지지선|저항선|지지 ?라인|저항 ?라인")
DRAW_VERBS = re.compile(r"그려|그리|표시|보여|찍어|그어")
SEARCH_VERBS = re.compile(r"찾아|검색|골라|추려|종목들|조건|스크리닝|필터")
PARTICLES = re.compile(r"(에\s*대해서|에\s*대해|에\s*관해|의|은|는|을|를|이|가|도|만|으로|로|에서|에)$")
STOPWORDS = {"올해", "연초", "최근", "기반으로", "기반", "기준으로", "큰", "작은", "채널", "추세선", "전고점", "전고점들", "전저점", "전저점들",
             "고점", "저점", "그려줘", "그려", "보여줘", "표시해줘", "차트", "차트에", "지지선", "저항선", "회귀", "평균"}


def _tokens(question: str) -> list[str]:
    words = re.split(r"[\s,.·?!()\[\]\"']+", question)
    out = []
    for word in words:
        cleaned = PARTICLES.sub("", word.strip())
        if len(cleaned) >= 2 and cleaned not in STOPWORDS and not re.fullmatch(r"\d+[개월년]?", cleaned):
            out.append(cleaned)
    return out


def resolve_stock(conn: sqlite3.Connection, question: str) -> dict | None:
    """질문 토큰을 종목으로 해소. 국내는 companies 정확 › 접두 › 포함, 대문자 1~5자는 미국 티커."""
    tokens = _tokens(question)
    for token in tokens:
        if re.fullmatch(r"[A-Z]{1,5}", token):
            from pipeline.us_data import resolve_us
            resolved = resolve_us(conn, token)
            if resolved:
                return {"code": token, "name": resolved[1] or token, "market": "us"}
    for order in ("corp_name = ?", "corp_name LIKE ? || '%'", "corp_name LIKE '%' || ? || '%'"):
        for token in sorted(tokens, key=len, reverse=True):
            if re.fullmatch(r"[가-힣A-Za-z0-9&]+", token) is None:
                continue
            row = conn.execute(f"SELECT stock_code, corp_name FROM companies WHERE stock_code IS NOT NULL AND {order} "
                               "ORDER BY LENGTH(corp_name) LIMIT 1", (token,)).fetchone()
            if row:
                return {"code": row["stock_code"], "name": row["corp_name"], "market": "kr"}
    return None


def interpret(conn: sqlite3.Connection, question: str) -> dict:
    """그리기 요청이면 매개변수를, 아니면 draw=False와 이유를 돌려준다. 모델 호출 없음."""
    text = question.strip()
    matched = []
    if not STRUCTURE_WORDS.search(text):
        return {"draw": False, "reason": "구조 단어(채널·추세선·고점/저점 연결·지지/저항선)가 없습니다."}
    if not DRAW_VERBS.search(text):
        return {"draw": False, "reason": "그리기 동사(그려·표시·보여)가 없습니다."}
    if SEARCH_VERBS.search(text):
        return {"draw": False, "reason": "검색 동사가 있어 조건 검색으로 처리합니다."}
    stock = resolve_stock(conn, text)
    if not stock:
        return {"draw": True, "code": None, "reason": "어느 종목인지 찾지 못했습니다. 종목 이름이나 코드를 적어주세요."}
    if "채널" in text:
        kind = "channel"; matched.append("채널")
    elif re.search(r"저점|지지|전저점", text):
        kind = "trendline_low"; matched.append("저점·지지 → 저점 추세선")
    elif re.search(r"고점|저항|전고점", text):
        kind = "trendline_high"; matched.append("고점·저항 → 고점 추세선")
    else:
        kind = "trendline_low"; matched.append("추세선 → 저점 추세선(기본)")
    window = "1y"
    if re.search(r"올해|연초|YTD|ytd", text):
        window = "ytd"; matched.append("올해 → 연초부터")
    elif (m := re.search(r"(\d{1,2})\s*개월", text)):
        window = f"{int(m.group(1))}m"; matched.append(f"{m.group(1)}개월")
    elif (m := re.search(r"(\d{1,2})\s*년", text)):
        window = f"{int(m.group(1))}y"; matched.append(f"{m.group(1)}년")
    swing = 5
    if re.search(r"큰|장기|주요|메이저|굵", text):
        swing = 10; matched.append("큰 → 스윙 폭 10(잔파동 무시)")
    elif re.search(r"작은|단기|세밀|잔", text):
        swing = 3; matched.append("작은 → 스윙 폭 3")
    fit = "regression" if re.search(r"회귀|평균|전체 고점|전체 저점", text) else "two_point"
    if fit == "regression":
        matched.append("회귀 적합")
    return {"draw": True, **stock, "kind": kind, "window": window, "swing": swing, "fit": fit, "matched": matched}
