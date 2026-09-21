"""종목 하나의 차트에 채널·추세선을 그리는 결정적 계산 (docs/specs/chart-structure.md, D-195).

"올해 전고점들을 기반으로 큰 채널을 그려줘"를 조건 검색이 아니라 그리기 요청으로 받는다.
스윙 검출·직선 적합은 가격 구조 전략(D-187)의 규칙을 그대로 쓰고, 모델 호출은 없다.
"""
from __future__ import annotations

import math
import re
import sqlite3
from datetime import date, timedelta

from pipeline.market_analysis.strategies import _fit_line, _pivot_indexes, normalize_condition
from pipeline.technical_scan import load_rows

KINDS = {"channel": "채널", "trendline_high": "고점 추세선", "trendline_low": "저점 추세선", "levels": "지지·저항 레벨"}
LEVEL_TOLERANCE = 0.015  # 스윙 가격이 서로 1.5% 안이면 같은 레벨
MAX_LEVELS = 6
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


def _levels(rows: list[dict], swing: int) -> dict:
    """수평 지지·저항: 스윙 고점·저점 가격을 1.5% 안에서 묶어 레벨로. 접촉 많은 순, 최대 6개."""
    used, touches, notes = swing, [], []
    while used >= MIN_SWING:
        touches = [(k, rows[k]["high"], "high") for k in _pivots(rows, used, "high", False)] + \
                  [(k, rows[k]["low"], "low") for k in _pivots(rows, used, "low", True)]
        if len(touches) >= 2:
            break
        used -= 1
    if len(touches) < 2:
        raise StructureUnavailable("기간이 짧거나 변동이 작아 스윙 점을 2개 이상 찾지 못했습니다. 기간을 늘리거나 스윙 폭을 줄여 보세요.")
    if used != swing:
        notes.append(f"스윙 폭 {swing}에서 스윙 점이 2개 미만이어서 {used}로 줄여 찾았습니다.")
    clusters: list[list[tuple[int, float, str]]] = []
    for item in sorted(touches, key=lambda t: t[1]):
        if clusters and abs(item[1] - clusters[-1][-1][1]) <= LEVEL_TOLERANCE * clusters[-1][-1][1]:
            clusters[-1].append(item)
        else:
            clusters.append([item])
    last = len(rows) - 1
    close = rows[last]["close"]
    levels = []
    for cluster in clusters:
        price = math.fsum(t[1] for t in cluster) / len(cluster)
        levels.append({"price": round(price, 4), "touches": len(cluster), "first": rows[min(t[0] for t in cluster)]["date"],
                       "last_touch": rows[max(t[0] for t in cluster)]["date"], "role": "resistance" if price > close else "support",
                       "sides": sorted({t[2] for t in cluster})})
    # 여러 번 닿은 레벨을 먼저, 남는 자리는 현재가에 가까운 단일 스윙으로 채운다(급등 종목은 고점대가 한 번씩만 닿는다).
    multi = sorted([l for l in levels if l["touches"] >= 2], key=lambda l: -l["touches"])[:MAX_LEVELS]
    singles = sorted([l for l in levels if l["touches"] < 2], key=lambda l: abs(l["price"] - close))
    chosen = multi + singles[:max(0, MAX_LEVELS - len(multi))]
    if not multi:
        notes.append("두 번 이상 닿은 레벨이 없어 현재가에 가까운 스윙 점을 레벨로 보였습니다.")
    lines = [{"id": f"level:{i}", "label": f"{'저항' if l['role'] == 'resistance' else '지지'} {l['touches']}회",
              "points": [{"time": l["first"], "value": l["price"]}, {"time": rows[last]["date"], "value": l["price"]}]} for i, l in enumerate(chosen)]
    above = [l for l in chosen if l["role"] == "resistance"]
    below = [l for l in chosen if l["role"] == "support"]
    nearest_resistance = min(above, key=lambda l: l["price"]) if above else None
    nearest_support = max(below, key=lambda l: l["price"]) if below else None
    summary = {"close": close, "levels": chosen, "sessions": len(rows), "slope_pct_per_session": None,
               "nearest_resistance": nearest_resistance["price"] if nearest_resistance else None,
               "nearest_support": nearest_support["price"] if nearest_support else None,
               "resistance_distance_pct": round((nearest_resistance["price"] / close - 1) * 100, 2) if nearest_resistance else None,
               "support_distance_pct": round((close / nearest_support["price"] - 1) * 100, 2) if nearest_support else None}
    pivots = [{"time": rows[k]["date"], "price": price, "side": side, "anchor": False} for k, price, side in touches]
    return {"kind": "levels", "fit": "two_point", "swing": used, "requested_swing": swing, "lines": lines, "pivots": pivots,
            "summary": summary, "notes": notes, "first": rows[0]["date"], "last": rows[last]["date"]}


def structure(rows: list[dict], kind: str, swing: int, fit: str = "two_point") -> dict:
    """기간 안 일봉(rows, 날짜 오름차순)에 구조를 그린다. 순수 계산."""
    if kind not in KINDS or fit not in FITS:
        raise StructureUnavailable("지원하지 않는 구조 또는 적합 방식입니다.")
    if not MIN_SWING <= swing <= MAX_SWING:
        raise StructureUnavailable("스윙 폭은 2~30 사이여야 합니다.")
    rows = [r for r in rows if all(isinstance(r.get(k), (int, float)) and math.isfinite(r[k]) and r[k] > 0 for k in ("open", "high", "low", "close"))]
    if len(rows) < 5:
        raise StructureUnavailable("기간 안에 유효한 시세가 5거래일 미만입니다.")
    if kind == "levels":
        return _levels(rows, swing)
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


def to_conditions(kind: str, swing: int, fit: str, sessions: int) -> list[dict]:
    """그린 구조를 가장 가까운 카탈로그 조건으로 옮긴다 (감시 규칙·검색 조건용, D-196).

    정확히 같은 선은 아니다: 카탈로그는 '최근 N개 스윙'으로 선을 다시 적합한다. 매개변수(스윙 폭·점 수·탐색 구간)는
    그린 구조에서 가져오고, 차이는 note로 알린다. 모든 결과는 normalize_condition을 통과한다.
    """
    lookback = max(20, min(250, sessions))
    width = max(1, min(30, swing))
    points = 2 if fit == "two_point" else 3
    base = {"pivot_width": width, "lookback": lookback}
    options = {
        "channel": [("channel_break_up", "채널 상단 돌파", {**base, "points": points, "method": "swing", "period": 60, "band_std": 2}),
                    ("channel_break_down", "채널 하단 이탈", {**base, "points": points, "method": "swing", "period": 60, "band_std": 2})],
        "trendline_high": [("trendline_break_up", "하락 추세선 상향 돌파", {**base, "points": points})],
        "trendline_low": [("trendline_break_down", "상승 추세선 하향 이탈", {**base, "points": points}),
                          ("trendline_support_hold", "상승 추세선 지지 반등", {**base, "points": points, "tolerance_pct": 1.5})],
        "levels": [("resistance_break", "전고점 돌파", {**base, "min_break_pct": 0}), ("support_break", "전저점 이탈", {**base, "min_break_pct": 0})],
    }[kind]
    out = []
    for strategy_id, label, params in options:
        condition = normalize_condition({"strategy_id": strategy_id, "params": params, "within_days": 1})
        out.append({"strategy_id": strategy_id, "label": label, "params": condition["params"], "within_days": 1,
                    "phrase": f"{label} (스윙 폭 {width}, 최근 {lookback}봉)",
                    "note": "카탈로그 조건은 최근 스윙으로 선을 다시 적합합니다. 그린 선과 매개변수는 같지만 기준점은 다를 수 있습니다."})
    return out


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
            "candles": candles, "conditions": to_conditions(result["kind"], result["swing"], result["fit"], len(inside)), **{**result, "notes": notes}}


# --- 질문 해석 (규칙) ------------------------------------------------------------------------

STRUCTURE_WORDS = re.compile(r"채널|추세선|고점.{0,4}(연결|선)|저점.{0,4}(연결|선)|전고점|전저점|지지선|저항선|지지 ?라인|저항 ?라인|지지.{0,3}저항|저항.{0,3}지지|레벨|매물대 ?선")
DRAW_VERBS = re.compile(r"그려|그리|표시|보여|찍어|그어")
SEARCH_VERBS = re.compile(r"찾아|검색|골라|추려|종목들|조건|스크리닝|필터")
PARTICLES = re.compile(r"(에\s*대해서|에\s*대해|에\s*관해|의|은|는|을|를|이|가|도|만|으로|로|에서|에)$")
STOPWORDS = {"올해", "연초", "최근", "기반으로", "기반", "기준으로", "큰", "작은", "채널", "추세선", "전고점", "전고점들", "전저점", "전저점들",
             "고점", "저점", "그려줘", "그려", "보여줘", "표시해줘", "차트", "차트에", "지지선", "저항선", "회귀", "평균", "레벨", "비교", "비교해서", "함께", "같이", "각각", "그리고", "와", "과"}


def _tokens(question: str) -> list[str]:
    words = re.split(r"[\s,.·?!()\[\]\"']+", question)
    out = []
    for word in words:
        cleaned = PARTICLES.sub("", word.strip())
        if len(cleaned) >= 2 and cleaned not in STOPWORDS and not re.fullmatch(r"\d+[개월년]?", cleaned):
            out.append(cleaned)
    return out


def _lookup(conn: sqlite3.Connection, token: str) -> dict | None:
    if re.fullmatch(r"[A-Z]{1,5}", token):
        from pipeline.us_data import resolve_us
        resolved = resolve_us(conn, token)
        return {"code": token, "name": resolved[1] or token, "market": "us"} if resolved else None
    if re.fullmatch(r"[가-힣A-Za-z0-9&]+", token) is None:
        return None
    for order in ("corp_name = ?", "corp_name LIKE ? || '%'", "corp_name LIKE '%' || ? || '%'"):
        row = conn.execute(f"SELECT stock_code, corp_name FROM companies WHERE stock_code IS NOT NULL AND {order} "
                           "ORDER BY LENGTH(corp_name) LIMIT 1", (token,)).fetchone()
        if row:
            return {"code": row["stock_code"], "name": row["corp_name"], "market": "kr"}
    return None


def resolve_stocks(conn: sqlite3.Connection, question: str) -> list[dict]:
    """질문 토큰을 종목들로 해소(등장 순서, 중복 제거). 국내는 companies 정확 › 접두 › 포함, 대문자 1~5자는 미국 티커."""
    found, seen = [], set()
    for raw in _tokens(question):
        # 나열 조사(와·과·랑)는 이름 끝에 붙어 오므로 원형과 뗀 형태를 차례로 본다
        variants = [raw] + [raw[:-len(suffix)] for suffix in ("이랑", "랑", "와", "과") if raw.endswith(suffix) and len(raw) > len(suffix) + 1]
        hit = None
        for token in variants:
            # 접두·포함 매칭은 짧은 토큰의 오탐이 크므로 3자 이상만
            hit = _lookup(conn, token) if (len(token) >= 3 or re.fullmatch(r"[A-Z]{1,5}", token)) else None
            if hit is None and len(token) >= 2:
                row = conn.execute("SELECT stock_code, corp_name FROM companies WHERE stock_code IS NOT NULL AND corp_name = ?", (token,)).fetchone()
                hit = {"code": row["stock_code"], "name": row["corp_name"], "market": "kr"} if row else None
            if hit:
                break
        if hit and hit["code"] not in seen:
            seen.add(hit["code"]); found.append(hit)
    return found


def resolve_stock(conn: sqlite3.Connection, question: str) -> dict | None:
    stocks = resolve_stocks(conn, question)
    return stocks[0] if stocks else None


ASSIST_SYSTEM = ("당신은 한국 주식 차트 요청에서 회사 이름만 뽑는다. 문장에 언급된 회사·종목 이름(한글 정식명 또는 미국 티커)을 등장 순서대로 "
                 "company_names 배열로 돌려준다. 조사(에 대해서·의·은/는)를 떼고, 없으면 빈 배열. 그 외 어떤 텍스트도 만들지 않는다.")


def model_assist(question: str) -> list[str]:
    """규칙이 종목을 못 찾을 때만 쓰는 보조: haiku 1콜로 회사 이름 후보를 뽑는다(도구 없음, $0.02·20초 상한)."""
    from pipeline.market_analysis.model import structured_call
    schema = {"type": "object", "properties": {"company_names": {"type": "array", "items": {"type": "string", "maxLength": 40}, "maxItems": 5}},
              "required": ["company_names"]}
    payload, _cost = structured_call(ASSIST_SYSTEM, {"question": question}, schema, budget=.02, timeout=20, model="haiku")
    names = payload.get("company_names") if isinstance(payload, dict) else None
    return [n.strip() for n in names if isinstance(n, str) and n.strip()][:5] if isinstance(names, list) else []


def interpret(conn: sqlite3.Connection, question: str, *, assist=model_assist) -> dict:
    """그리기 요청이면 매개변수를, 아니면 draw=False와 이유를 돌려준다. 종목을 못 찾을 때만 모델 보조(haiku 1콜)."""
    text = question.strip()
    matched = []
    if not STRUCTURE_WORDS.search(text):
        return {"draw": False, "reason": "구조 단어(채널·추세선·고점/저점 연결·지지/저항선·레벨)가 없습니다."}
    if not DRAW_VERBS.search(text):
        return {"draw": False, "reason": "그리기 동사(그려·표시·보여)가 없습니다."}
    if SEARCH_VERBS.search(text):
        return {"draw": False, "reason": "검색 동사가 있어 조건 검색으로 처리합니다."}
    stocks = resolve_stocks(conn, text)
    assisted = False
    if not stocks and assist is not None:
        try:
            names = assist(text)
        except Exception:  # 보조 실패는 조용히 넘기지 않고 이유에 남긴다
            names = []
            matched.append("모델 보조 실패")
        for name in names:
            hit = _lookup(conn, name) or _lookup(conn, name.replace(" ", ""))
            if hit and hit["code"] not in {s["code"] for s in stocks}:
                stocks.append(hit)
        assisted = bool(stocks)
    if not stocks:
        return {"draw": True, "code": None, "reason": "어느 종목인지 찾지 못했습니다. 종목 이름이나 코드를 적어주세요.", "matched": matched}
    if assisted:
        matched.append("종목 이름은 모델 보조(haiku)로 찾음")
    stock = stocks[0]
    if re.search(r"레벨|지지.{0,3}저항|저항.{0,3}지지|매물대 ?선", text) or (re.search(r"지지선|저항선", text) and not re.search(r"고점|저점|추세|연결", text)):
        kind = "levels"; matched.append("지지·저항 → 수평 레벨")
    elif "채널" in text:
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
    if len(stocks) > 1:
        matched.append(f"종목 {len(stocks)}개 비교")
    return {"draw": True, **stock, "codes": [s["code"] for s in stocks], "names": [s["name"] for s in stocks],
            "kind": kind, "window": window, "swing": swing, "fit": fit, "matched": matched}
