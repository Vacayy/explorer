"""미국 수요 기업 분기 실적 — 밸류체인 최종 수요 관측용 (docs/specs/value-chain.md §6, LLM 0).

원천: SEC XBRL companyfacts(`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`, 무료, `.env SEC_USER_AGENT` 필요).
- AI 데이터센터 수요: 하이퍼스케일러 설비투자(MSFT·GOOGL·AMZN·META·ORCL)
- AI 가속기: 엔비디아·AMD 매출
- 스마트폰 수요: 애플 매출
분기 값 만들기: 3개월(80~100일) 값이 있으면 그대로, 없으면 같은 회계연도 시작의 누적값끼리 차감한다
(현금흐름표 설비투자는 10-Q에서 연초부터 누적으로 보고된다 — 애플 등). 분기 키는 끝 날짜의 달력 분기('YYYY-03|06|09|12').
계정은 후보 중 가장 최근까지 보고된 것을 쓴다(아마존은 설비투자를 PaymentsToAcquireProductiveAssets로 바꿨다).
"""
from __future__ import annotations

from datetime import date

# (티커, 지표, 용도)
TARGETS = [
    ("MSFT", "capex", "ai"), ("GOOGL", "capex", "ai"), ("AMZN", "capex", "ai"), ("META", "capex", "ai"), ("ORCL", "capex", "ai"),
    ("NVDA", "revenue", "ai_accel"), ("AMD", "revenue", "ai_accel"), ("AVGO", "revenue", "ai_accel"),
    ("AAPL", "revenue", "mobile"),
    ("QCOM", "revenue", "mobile_soc"),
    ("INTC", "revenue", "cpu"),
    ("AMAT", "revenue", "dep_etch"), ("LRCX", "revenue", "dep_etch"), ("KLAC", "revenue", "metrology"),
    # AI 프론티어 랩 수요의 대리 — 랩과 맺은 다년 컴퓨트 계약이 쌓이는 수주잔고(RPO, 분기 말 시점 잔액)
    ("ORCL", "rpo", "frontier"), ("CRWV", "rpo", "frontier"),
    # 네트워크·인터커넥트(2026-10-18 조사: AI 데이터센터 비중이 공시로 확인된 회사만)
    ("ANET", "revenue", "dc_switch"), ("CLS", "revenue", "dc_switch"), ("CIEN", "revenue", "dci"),
    ("ALAB", "revenue", "ic_link"), ("CRDO", "revenue", "ic_link"), ("MRVL", "revenue", "ic_link"),
    ("APH", "revenue", "copper"), ("COHR", "revenue", "optics"), ("LITE", "revenue", "optics"), ("FN", "revenue", "optics"),
    # 전력·냉각
    ("MPWR", "revenue", "power_semi"), ("VRT", "revenue", "dc_infra"), ("NVT", "revenue", "dc_infra"), ("MOD", "revenue", "dc_infra"),
    ("GEV", "revenue", "power_grid"),
    # 자본 조달 — 장기채 발행액(현금흐름표, 분기 누적은 차감). 분기마다 들쭉날쭉해 최근 4분기 합으로 본다(TTM)
    ("MSFT", "debt_issue", "funding"), ("GOOGL", "debt_issue", "funding"), ("AMZN", "debt_issue", "funding"),
    ("META", "debt_issue", "funding"), ("ORCL", "debt_issue", "funding"), ("CRWV", "debt_issue", "funding"),
]
# SEC에 분기 XBRL이 없는 회사(20-F 연간뿐) — yfinance 최근 분기를 받아 쌓는다(매 수집마다 upsert라 이력이 늘어난다)
YF_TARGETS: list[tuple[str, str, str, str]] = []   # ASML은 SEC 6-K 보도자료(pipeline/asml_6k)로 옮겼다 — 공식 원천이 이긴다
# 다른 수집기가 us_quarterly에 넣는 회사(집계·상세에 포함) — (티커, 지표, 용도)
EXTERNAL = [("ASML", "revenue", "litho")]   # pipeline/asml_6k: SEC 6-K 분기 보도자료, 2010~
FX_CONST = {"EUR": 1.1}   # 합산용 고정 환율 — 회사별 YoY가 원통화 YoY와 같게 유지된다(환율 변동을 섞지 않음)
TAGS = {
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax"],   # LITE는 2025-03 이후 이 계정
    "rpo": ["RevenueRemainingPerformanceObligation"],
    "debt_issue": ["ProceedsFromIssuanceOfLongTermDebt", "ProceedsFromIssuanceOfSeniorLongTermDebt", "ProceedsFromIssuanceOfDebt",
                   "ProceedsFromIssuanceOfUnsecuredDebt",
                   "ProceedsFromDebtMaturingInMoreThanThreeMonths",   # MSFT
                   "ProceedsFromDebtNetOfIssuanceCosts"],             # GOOGL
}
TTM = {"funding"}          # 최근 4분기 합으로 YoY — 발행·인수처럼 분기마다 들쭉날쭉한 지표
INSTANT = {"rpo"}          # 기간이 아니라 시점 잔액 — 분기 말 값을 그대로 쓴다


def _quarter_key(end: str) -> str:
    """끝 날짜 → 달력 분기 끝 'YYYY-MM' (애플 12-27 → 12월, 오라클 11-30 → 12월로 반올림하지 않도록 15일을 빼 판단)"""
    d = date.fromisoformat(end)
    y, m = d.year, d.month
    if d.day < 15:                       # 1~14일에 끝나면 직전 달 분기로 본다
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    qm = ((m - 1) // 3 + 1) * 3
    return f"{y}-{qm:02d}"


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def quarterly(entries: list[dict]) -> dict[str, float]:
    """XBRL 기간 값들 → 분기 값 {분기키: 값}"""
    by: dict[tuple[str, str], dict] = {}
    for e in entries:
        if not e.get("start") or e.get("form") not in ("10-Q", "10-K", "10-Q/A", "10-K/A"):
            continue
        k = (e["start"], e["end"])
        if k not in by or e.get("filed", "") > by[k].get("filed", ""):
            by[k] = e
    out: dict[str, float] = {}
    for (s, t), e in by.items():                       # 1) 3개월 값
        if 80 <= _days(s, t) <= 100:
            out[_quarter_key(t)] = e["val"]
    groups: dict[str, list[tuple[str, float]]] = {}
    for (s, t), e in by.items():                       # 2) 같은 시작의 누적값 차감
        if _days(s, t) > 100:
            groups.setdefault(s, []).append((t, e["val"]))
    for s, cums in groups.items():
        q1 = [(t, by[(ss, t)]["val"]) for (ss, t) in by if ss == s and 80 <= _days(s, t) <= 100]   # 회계연도 첫 분기
        chain = sorted(q1 + cums)
        for (t0, v0), (t1, v1) in zip(chain, chain[1:]):
            if 80 <= _days(t0, t1) <= 100 and _quarter_key(t1) not in out:
                out[_quarter_key(t1)] = v1 - v0
    return out


def quarterly_instant(entries: list[dict]) -> dict[str, float]:
    """시점 값(잔액) → 분기 말 값 {분기키: 값}. 같은 날짜는 가장 늦게 제출된 값"""
    by: dict[str, dict] = {}
    for e in entries:
        if e.get("form") not in ("10-Q", "10-K", "10-Q/A", "10-K/A"):
            continue
        if e["end"] not in by or e.get("filed", "") > by[e["end"]].get("filed", ""):
            by[e["end"]] = e
    return {_quarter_key(end): e["val"] for end, e in sorted(by.items())}


def _pick_tag(gaap: dict, metric: str) -> tuple[str, list[dict]] | None:
    best = None
    for tag in TAGS[metric]:
        units = gaap.get(tag, {}).get("units", {}).get("USD")
        if units:
            key = (max(u["end"] for u in units), len(units))    # 끝 날짜가 같으면 사실이 많은 계정(LITE: 연간만 남은 계정 회피)
            if best is None or key > best[0]:
                best = (key, tag, units)
    return (best[1], best[2]) if best else None


def collect() -> dict:
    """대상 티커의 분기 값을 받아 us_quarterly에 upsert. 한 티커 실패는 남기고 계속"""
    import config  # noqa: F401 — .env(SEC_USER_AGENT)
    from database import get_connection
    from pipeline.sec_filings import _get, cik_map
    ciks = cik_map()
    stored, failed = 0, []
    conn = get_connection()
    try:
        for ticker, metric, use in TARGETS:
            try:
                facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{ciks[ticker]:010d}.json", as_json=True)
                picked = _pick_tag(facts["facts"]["us-gaap"], metric)
                if not picked:
                    failed.append(f"{ticker}: {metric} 계정 없음")
                    continue
                tag, units = picked
                for q, v in (quarterly_instant(units) if metric in INSTANT else quarterly(units)).items():
                    conn.execute("INSERT INTO us_quarterly (ticker, q, metric, value, tag, use_key, fetched_at) VALUES (?,?,?,?,?,?, datetime('now')) "
                                 "ON CONFLICT(ticker, q, metric) DO UPDATE SET value=excluded.value, tag=excluded.tag, "
                                 "use_key=excluded.use_key, fetched_at=excluded.fetched_at", (ticker, q, metric, v, tag, use))
                    stored += 1
                conn.commit()
            except Exception as e:  # noqa: BLE001
                failed.append(f"{ticker}: {type(e).__name__}")
    finally:
        conn.close()
    stored_yf, failed_yf = collect_yf()
    stored += stored_yf
    failed += failed_yf
    try:                                  # ASML 최근 2년 6-K만 다시 확인(전체 이력은 한 번 백필함)
        from pipeline.asml_6k import collect as collect_asml
        r = collect_asml(since_year=date.today().year - 1)
        stored += r.get("stored", 0)
        if r.get("status") == "error":
            failed.append(f"ASML 6-K: {r.get('error') or 'error'}")
    except Exception as e:  # noqa: BLE001
        failed.append(f"ASML 6-K: {type(e).__name__}")
    return {"stored": stored, "failed": failed, "status": "error" if not stored else "partial" if failed else "ok"}


def collect_yf() -> tuple[int, list[str]]:
    """yfinance 분기 매출(최근 4~5분기) → us_quarterly. 고정 환율로 USD 환산, tag에 원통화 표시"""
    import yfinance as yf
    from database import get_connection
    stored, failed = 0, []
    conn = get_connection()
    try:
        for ticker, metric, use, ccy in YF_TARGETS:
            try:
                q = yf.Ticker(ticker).quarterly_income_stmt
                row = q.loc["Total Revenue"].dropna()
                for col, v in row.items():
                    end = str(col)[:10]
                    conn.execute("INSERT INTO us_quarterly (ticker, q, metric, value, tag, use_key, fetched_at) VALUES (?,?,?,?,?,?, datetime('now')) "
                                 "ON CONFLICT(ticker, q, metric) DO UPDATE SET value=excluded.value, tag=excluded.tag, use_key=excluded.use_key, "
                                 "fetched_at=excluded.fetched_at",
                                 (ticker, _quarter_key(end), metric, float(v) * FX_CONST.get(ccy, 1.0), f"yfinance:Total Revenue({ccy}×{FX_CONST.get(ccy, 1.0)})", use))
                    stored += 1
                conn.commit()
            except Exception as e:  # noqa: BLE001
                failed.append(f"{ticker}: {type(e).__name__}")
    finally:
        conn.close()
    return stored, failed


def demand_series(conn, use_key: str) -> dict[str, float]:
    """용도별 분기 YoY(%) — 그 분기와 전년 같은 분기에 둘 다 값이 있는 회사들만 합산(같은 회사 묶음끼리 비교).
    구성 회사의 절반 이상이 짝지어질 때만 낸다 — 이력이 짧은 회사(ASML 등)가 끼어도 칸 전체 이력이 줄지 않게"""
    tickers = [t for t, _, u in TARGETS + EXTERNAL + [(a, b, c) for a, b, c, _ in YF_TARGETS] if u == use_key]
    vals: dict[str, dict[str, float]] = {}
    for r in conn.execute(f"SELECT ticker, q, value FROM us_quarterly WHERE use_key=? AND ticker IN "
                          f"({','.join('?' * len(tickers))})", (use_key, *tickers)):
        vals.setdefault(r["q"], {})[r["ticker"]] = r["value"]
    if use_key in TTM:                    # 회사별 최근 4분기 합으로 바꾼다(4분기가 연속으로 있을 때만)
        def back(q, k):
            y, m = int(q[:4]), int(q[5:])
            i = y * 12 + m - 1 - 3 * k
            return f"{i // 12}-{i % 12 + 1:02d}"
        # 발행이 없는 분기는 10-Q가 항목을 아예 보고하지 않는다 → 그 회사의 보고 기간 안의 빈 분기는 0으로 본다
        span = {t: (min(q for q in vals if t in vals[q]), max(q for q in vals if t in vals[q])) for t in tickers
                if any(t in v for v in vals.values())}
        ttm: dict[str, dict[str, float]] = {}
        for q in sorted(vals):
            for t, (lo, hi) in span.items():
                window = [back(q, k) for k in range(4)]
                if window[-1] < lo or q > hi:
                    continue
                ttm.setdefault(q, {})[t] = sum(vals.get(w, {}).get(t, 0.0) for w in window)
        vals = ttm
    out = {}
    for q, cur in vals.items():
        prev = vals.get(f"{int(q[:4]) - 1}{q[4:]}", {})
        both = [t for t in cur if t in prev and prev[t]]
        if len(both) * 2 >= len(tickers):
            out[q] = (sum(cur[t] for t in both) / sum(prev[t] for t in both) - 1) * 100
    return dict(sorted(out.items()))


NAMES = {"MSFT": "마이크로소프트", "GOOGL": "알파벳(구글)", "AMZN": "아마존", "META": "메타", "ORCL": "오라클",
         "NVDA": "엔비디아", "AMD": "AMD", "AVGO": "브로드컴", "AAPL": "애플", "QCOM": "퀄컴", "INTC": "인텔",
         "AMAT": "어플라이드 머티리얼즈", "KLAC": "KLA", "LRCX": "램리서치", "ASML": "ASML", "CRWV": "코어위브",
         "ANET": "아리스타", "CLS": "셀레스티카", "CIEN": "시에나", "ALAB": "아스테라랩스", "CRDO": "크레도", "MRVL": "마벨",
         "APH": "앰페놀", "COHR": "코히런트", "LITE": "루멘텀", "FN": "패브리넷", "MPWR": "모놀리식파워", "VRT": "버티브",
         "NVT": "엔벤트", "MOD": "모딘", "GEV": "GE버노바"}


def members(conn, use_key: str) -> list[dict]:
    """용도별 구성 회사의 최신 분기 값과 YoY — 수요 칸 상세"""
    out = []
    for ticker, metric, use in TARGETS + EXTERNAL + [(a, b, c) for a, b, c, _ in YF_TARGETS]:
        if use != use_key:
            continue
        rows = {r["q"]: r["value"] for r in conn.execute(
            "SELECT q, value FROM us_quarterly WHERE ticker=? AND metric=? ORDER BY q", (ticker, metric))}
        if not rows:
            continue
        q = max(rows)
        prev = f"{int(q[:4]) - 1}{q[4:]}"
        # 발행처럼 분기마다 들쭉날쭉한 지표(TTM)는 회사별 분기 YoY가 뜻이 없어 내지 않는다
        yoy = (rows[q] / rows[prev] - 1) * 100 if rows.get(prev) and use not in TTM else None
        qs = sorted(rows)
        qoq = rows[q] - rows[qs[-2]] if metric in INSTANT and len(qs) > 1 else None   # 잔액은 전 분기 대비 순증가가 핵심
        out.append({"ticker": ticker, "name": NAMES.get(ticker, ticker),
                    "metric": {"capex": "설비투자", "rpo": "수주잔고(RPO)", "debt_issue": "장기채 발행"}.get(metric, "매출"),
                    "q": q, "value": rows[q], "yoy": round(yoy, 1) if yoy is not None else None, "qoq_delta": qoq})
    return out
