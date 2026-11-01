"""ASML 분기 매출·순수주 — SEC EDGAR 6-K 실적 보도자료(EX-99.1)에서 파싱 (밸류체인 반도체 장비 칸, LLM 0).

ASML은 20-F 연간만 XBRL로 내고 분기 XBRL이 없다 → yfinance는 최근 4~5분기뿐이라 이력이 짧다.
분기 실적 보도자료는 1·4·7·10월 6-K의 EX-99.1로 2009년부터 SEC에 올라와 있어 여기서 이력을 만든다.

파싱 순서(보도자료 형식이 연대별로 다르다):
1. 보고 분기: 'published its Q3 2020 results' / 'publishes its 2016 third-quarter results' / 'announces 2010 third quarter results'
2. 값: 요약표('(Figures in millions of euros ...)' 아래 기간 머리 'Q2 2016 | Q3 2016' + 'Net sales' 행)에서 보고 분기 열.
   요약표가 없는 옛 형식(2009~2012)은 문장 'Q3 2010 net sales of EUR 1,176 million'.
   표와 첫머리 요약 문장('Q3 net sales of EUR 1.81 billion')이 둘 다 있으면 문장의 반올림 범위를 벗어날 때 값을 버린다(열을 잘못 짚은 것).
순수주(net bookings): 2026 Q1부터 ASML이 분기 공시를 중단 → None(0이 아님). 2013년 전후 일부는 'excluding EUV'로만 공시 → tag에 표시.
저장: us_quarterly에 EUR × FX_CONST['EUR'](고정 환율, YoY가 원통화와 같게) — 공식 원천이라 같은 분기의 yfinance 행을 덮어쓴다.
"""
from __future__ import annotations

import re
import time

CIK = 937966
TICKER = "ASML"
PAUSE = 0.15          # sec_filings._get이 0.15초 쉬므로 합쳐 요청 간 0.3초(초당 5회 이하)
RESULT_MONTHS = ("01", "04", "07", "10")
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"


def _qkey(qn: int, year: int) -> str:
    return f"{year}-{qn * 3:02d}"


def _reported_quarter(text: str) -> tuple[int, int] | None:
    """보도자료가 보고하는 분기 (분기번호, 연도). 다음 분기 가이던스('expects Q4 2016')를 집지 않도록 발표 문장을 먼저 본다"""
    m = re.search(r"(?:publishe[sd]|announces)\s+(?:its\s+)?(?:Q([1-4])\s+(\d{4})|(\d{4})\s+(first|second|third|fourth)[\s-]+quarter)", text, re.I)
    if m:
        return (int(m.group(1)), int(m.group(2))) if m.group(1) else (_ORD[m.group(4).lower()], int(m.group(3)))
    m = re.search(r"Q([1-4])\s+(\d{4})\s+(?:total\s+)?net\s+sales", text, re.I)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _to_eur(num: str, unit: str) -> tuple[float, float]:
    """(값, 반올림 허용오차) — '€7.5 billion'은 ±0.05bn, 'EUR 1,176 million'은 ±0.5m"""
    scale = 1e9 if unit.lower().startswith("b") else 1e6
    decimals = len(num.split(".")[1]) if "." in num else 0
    return float(num.replace(",", "")) * scale, 0.5 * 10 ** -decimals * scale


_PERIOD = r"(?:Q[1-4]|FY|YTD)\s*\d{4}"


def _table(text: str) -> tuple[list[str], str] | None:
    """요약표 (기간 머리 목록, 'Net sales' 행부터의 본문). 머리는 매출 행 바로 위의 기간만 있는 줄들
    ('Q3 2013' / 'Q2 2013' 세로 나열, 또는 '(Figures ...) | Q3 2024 | | Q4 2024' 한 줄)이다"""
    row = re.search(r"^[ \t]*(?:Total\s+)?Net\s+sales[ \t]*(?:\||$)", text, re.I | re.M)
    if not row:
        return None
    periods: list[str] = []
    for line in reversed(text[:row.start()].rstrip("\n").split("\n")):
        rest = re.sub(r"\(Figures in millions of euros[^)]*\)", "", line, flags=re.I).replace("|", " ").strip()
        if not rest or rest.lower() == "notes":          # 빈 줄·'Notes' 열 머리(값 없음)
            continue
        if not re.fullmatch(rf"(?:{_PERIOD}(?:\s+\d)?\s*)+", rest):    # 기간 뒤 각주 숫자('Q4 2017 1') 허용
            break
        periods = [re.sub(r"^(Q[1-4]|FY|YTD)\s*", r"\1 ", p) for p in re.findall(_PERIOD, rest)] + periods
    return (periods, text[row.start():]) if periods else None


def _row_values(body: str, label: str, n: int) -> list[float]:
    """표 본문에서 label 행의 값(EUR) n개까지. 각주 표시('Net bookings 2', '*', '(3)', '9,186 | 2')는 버린다 —
    금액 행(백만 유로)에 한 자리 수 값은 없으므로 맨 한 자리 정수는 각주로 본다"""
    row = re.search(rf"^[ \t]*{label}(?:\s*(?:\*|\(\d\)|\d))?[ \t]*(?:\||$)", body[:6000], re.I | re.M)
    if not row:
        return []
    vals: list[float] = []
    for line in body[row.end():].split("\n"):
        if vals and re.match(r"\s*[A-Za-z(.…]", line):
            break
        vals += [float(v.replace(",", "")) * 1e6 for v in re.findall(_NUM, line) if not re.fullmatch(r"\d", v)]
        if len(vals) >= n:
            break
    return vals


def _table_value(text: str, label: str, period: str) -> float | None:
    t = _table(text)
    if not t or period not in t[0]:
        return None
    periods, body = t
    vals = _row_values(body, label, len(periods))
    idx = periods.index(period)
    return vals[idx] if len(vals) > idx else None


def _prose_value(text: str, what: str, qn: int, year: int) -> tuple[float, float] | None:
    """문장에서 'Q3 2010 net sales of EUR 1,176 million' / 'Q3 total net sales of €7.5 billion' / 'net bookings in Q4 of €7.1 billion'"""
    cur = r"(?:EUR\s*|€\s*)"
    q = rf"Q{qn}(?:\s+{year})?"
    pats = [rf"\b{q}\s+(?:total\s+)?{what}(?:,?\s+excluding\s+EUV)?\s+(?:of|(?:is\s+)?valued\s+at|totaled|were)\s+{cur}({_NUM})\s*(million|billion)",
            rf"\b{what}\s+in\s+{q}\s+of\s+{cur}({_NUM})\s*(million|billion)"]
    for p in pats:
        m = re.search(p, text, re.I)
        if m:
            return _to_eur(m.group(1), m.group(2))
    return None


def _pick(table: float | None, prose: tuple[float, float] | None) -> float | None:
    """표 값 우선. 문장 값이 있으면 그 반올림 범위 안에 들어야 한다 — 벗어나면 표 열을 잘못 짚은 것이라 버린다"""
    if prose is None:
        return table
    value, tol = prose
    if table is not None and abs(table - value) > tol * 1.01 + 1e6:
        return None
    return table if table is not None else value


def parse_press_release(text: str) -> dict:
    """ASML 실적 보도자료 평문 → {"quarter": "YYYY-MM"|None, "net_sales_eur", "bookings_eur", "bookings_scope", "comparatives"}.
    bookings_scope는 'excl_euv'(EUV 제외 공시) 또는 None. comparatives는 요약표의 다른 분기 열 매출 {"YYYY-MM": EUR}
    (해당 분기 보도자료를 못 읽었을 때만 메우는 용도)"""
    rq = _reported_quarter(text)
    out = {"quarter": None, "net_sales_eur": None, "bookings_eur": None, "bookings_scope": None, "comparatives": {}}
    if not rq:
        return out
    qn, year = rq
    out["quarter"] = _qkey(qn, year)
    period = f"Q{qn} {year}"
    out["net_sales_eur"] = _pick(_table_value(text, r"(?:Total\s+)?net\s+sales", period),
                                 _prose_value(text, r"net\s+sales", qn, year))
    t_book = _table_value(text, r"Net\s+bookings", period)
    t_excl = _table_value(text, r"Net\s+bookings,?\s+excluding\s+EUV", period)
    if t_book is None and (t_excl is not None or re.search(rf"\bQ{qn}(?:\s+{year})?\s+net\s+bookings,?\s+excluding\s+EUV", text, re.I)):
        out["bookings_scope"] = "excl_euv"
    out["bookings_eur"] = _pick(t_book if t_book is not None else t_excl,
                                _prose_value(text, r"net\s+bookings", qn, year))
    t = _table(text)
    if t:
        vals = _row_values(t[1], r"(?:Total\s+)?Net\s+sales", len(t[0]))
        for p, v in zip(t[0], vals):
            m = re.fullmatch(r"Q([1-4]) (\d{4})", p)
            if m and p != period:
                out["comparatives"][_qkey(int(m.group(1)), int(m.group(2)))] = v
    return out


def _expected_quarter(filing_date: str) -> str:
    """1월 공시 → 전년 Q4, 4월 → Q1, 7월 → Q2, 10월 → Q3"""
    y, m = int(filing_date[:4]), int(filing_date[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def _all_quarters(since_year: int, last: str) -> list[str]:
    out, y = [], since_year
    while True:
        for mm in ("03", "06", "09", "12"):
            k = f"{y}-{mm}"
            if k > last:
                return out
            out.append(k)
        y += 1


def collect(since_year: int = 2010) -> dict:
    """6-K 실적 보도자료를 훑어 us_quarterly(ASML, revenue/bookings)에 upsert"""
    import config  # noqa: F401 — .env(SEC_USER_AGENT)
    from database import get_connection
    from pipeline.sec_filings import _get, exhibits, to_text
    from pipeline.us_fundamentals import FX_CONST

    sub = _get(f"https://data.sec.gov/submissions/CIK{CIK:010d}.json", as_json=True)
    blocks = [sub["filings"]["recent"]]
    for f in sub["filings"].get("files", []):          # 오래된 공시 페이지(현재 ASML은 recent에 다 들어 있다)
        blocks.append(_get(f"https://data.sec.gov/submissions/{f['name']}", as_json=True))
    filings = []
    for b in blocks:
        for i, form in enumerate(b["form"]):
            fd = b["filingDate"][i]
            if form == "6-K" and fd[5:7] in RESULT_MONTHS and int(fd[:4]) >= since_year:
                filings.append((fd, b["accessionNumber"][i]))
    filings.sort(reverse=True)

    fx = FX_CONST["EUR"]
    parsed: dict[str, dict] = {}
    errors: list[str] = []
    for fd, acc in filings:
        exp = _expected_quarter(fd)
        if exp in parsed and parsed[exp]["net_sales_eur"] is not None:
            continue                                     # 같은 달의 다른 6-K(AGM·자사주 등)는 건너뛴다
        try:
            ex = next((e for e in exhibits(CIK, acc) if e["type"] == "EX-99.1"), None)
            time.sleep(PAUSE)
            if not ex:
                continue
            r = parse_press_release(to_text(_get(ex["url"])))
            time.sleep(PAUSE)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{fd} {acc}: {type(e).__name__}")
            continue
        if r["quarter"] != exp:
            continue                                     # 실적 보도자료가 아님(또는 다른 분기를 말함)
        if r["net_sales_eur"] is None:
            errors.append(f"{fd} {acc}: {exp} 보도자료인데 매출을 못 읽음")
        if exp not in parsed or (parsed[exp]["net_sales_eur"] is None and r["net_sales_eur"] is not None):
            parsed[exp] = r

    # 자기 보도자료로 못 읽은 분기는 다음 분기 보도자료 요약표의 비교 열로 메운다(tag로 구분)
    filled: dict[str, float] = {}
    for q, r in parsed.items():
        for cq, v in r["comparatives"].items():
            if (cq not in parsed or parsed[cq]["net_sales_eur"] is None) and cq not in filled:
                filled[cq] = v

    stored = 0
    conn = get_connection()
    try:
        sql = ("INSERT INTO us_quarterly (ticker, q, metric, value, tag, use_key, fetched_at) VALUES (?,?,?,?,?,?, datetime('now')) "
               "ON CONFLICT(ticker, q, metric) DO UPDATE SET value=excluded.value, tag=excluded.tag, "
               "use_key=excluded.use_key, fetched_at=excluded.fetched_at")
        for q, r in sorted(parsed.items()):
            if q < f"{since_year}-01":
                continue
            if r["net_sales_eur"] is not None:
                conn.execute(sql, (TICKER, q, "revenue", r["net_sales_eur"] * fx, f"sec-6k:net sales(EUR×{fx})", "litho"))
                stored += 1
            if r["bookings_eur"] is not None:
                scope = ", excl EUV" if r["bookings_scope"] == "excl_euv" else ""
                conn.execute(sql, (TICKER, q, "bookings", r["bookings_eur"] * fx, f"sec-6k:net bookings{scope}(EUR×{fx})", "litho_bookings"))
                stored += 1
        for q, v in sorted(filled.items()):
            if q >= f"{since_year}-01":
                conn.execute(sql, (TICKER, q, "revenue", v * fx, f"sec-6k:net sales(EUR×{fx}, 다음 분기 보도자료 비교열)", "litho"))
                stored += 1
        conn.commit()
    finally:
        conn.close()

    have = sorted({q for q, r in parsed.items() if r["net_sales_eur"] is not None} | set(filled))
    have = [q for q in have if q >= f"{since_year}-01"]
    expected = _all_quarters(since_year, max(have)) if have else []
    missing = [q for q in expected if q not in have]
    no_bookings = [q for q in expected if q in parsed and parsed[q]["bookings_eur"] is None]
    status = "error" if not have else "partial" if missing or errors else "ok"
    return {"stored": stored, "quarters": len(have), "filled_from_comparatives": sorted(q for q in filled if q >= f"{since_year}-01"),
            "range": (have[0], have[-1]) if have else None,
            "missing": missing, "bookings_missing": no_bookings, "errors": errors, "status": status}
