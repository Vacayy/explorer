"""미국 기업 고객 집중도 — 10-K/10-Q가 주석에 공시하는 '매출(또는 매출채권)의 10% 이상 고객' 비중 (LLM 0).

원천: SEC EDGAR 공시별 XBRL 인스턴스(`*_htm.xml`). companyfacts API는 차원(dimension) 붙은 값을 빼고 주므로
고객별 비중은 공시 원본 인스턴스를 직접 읽어야 한다.
- 값: us-gaap:ConcentrationRiskPercentage1 (소수 0.12 → 12.0%로 저장)
- 고객: srt:MajorCustomersAxis 멤버의 로컬명에서 'Member'를 뗀 것(nvda:CustomerAMember → CustomerA).
  이 축이 없는 값(지역·제품 집중도 등)은 버린다.
- 기준: ConcentrationRiskByBenchmarkAxis 멤버 이름에 Receivable → receivables, Revenue/Sales → revenue. 그 밖·없음은 버린다.
- 유형: ConcentrationRiskByTypeAxis가 있으면 CustomerConcentrationRiskMember만(공급자·신용 집중도 제외).
- 기간: 맥락 기간 길이로 Q(≤100일)·FY(≥340일)·YTD(그 사이 누적)·I(시점).
그 밖 차원(사업부 귀속 등)은 extra_dims에 남긴다 — NVDA는 '전체 매출의 22%, Compute & Networking 귀속'을 사업부 축과 함께 태깅한다.
지역 축이 붙은 값(NVDA '대만 청구 매출 중 미국·유럽계 최종 고객 76%')은 개별 고객 비중이 아니라 버린다.
같은 기간이 여러 공시에 나오면(전년 비교치) 최근 공시가 그 (기간·종류·기준) 묶음을 통째로 대체한다 — 익명 멤버 이름이
공시마다 바뀌어(NVDA 전년 비교치 CustomerA → RevenueCustomer5) 행 단위 덮어쓰기로는 같은 고객이 중복된다.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import date

TICKERS = ["NVDA", "AMD", "AVGO", "QCOM", "INTC", "AMAT", "KLAC", "LRCX", "MU", "CRWV", "ANET", "CRDO", "ALAB",
           "COHR", "LITE", "FN", "VRT", "MPWR", "AAPL", "ORCL", "MSFT"]
N_10Q = 6
PAUSE = 0.25   # sec_filings._get 자체 0.15초에 더해 — 공시 하나당 요청 2번(index·instance)

CUSTOMER_AXIS = "MajorCustomersAxis"
BENCHMARK_AXIS = "ConcentrationRiskByBenchmarkAxis"
TYPE_AXIS = "ConcentrationRiskByTypeAxis"
FACT = "ConcentrationRiskPercentage1"
GEO_AXIS = "StatementGeographicalAxis"


def _local(qname: str) -> str:
    """'nvda:CustomerAMember' 또는 '{ns}Tag' → 로컬명."""
    return qname.rsplit("}", 1)[-1].rsplit(":", 1)[-1].strip()


def _benchmark(member: str | None) -> str | None:
    if not member:
        return None
    m = _local(member)
    if "Receivable" in m:
        return "receivables"
    if "Revenue" in m or "Sales" in m:
        return "revenue"
    return None


def _period_kind(start: str | None, end: str) -> str:
    if not start:
        return "I"
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    if days <= 100:
        return "Q"
    if days >= 340:
        return "FY"
    return "YTD"


def _contexts(root: ET.Element) -> dict[str, dict]:
    out = {}
    for ctx in root.iter():
        if _local(ctx.tag) != "context":
            continue
        start = end = instant = None
        dims: dict[str, str] = {}
        for el in ctx.iter():
            name = _local(el.tag)
            if name == "startDate":
                start = (el.text or "").strip()
            elif name == "endDate":
                end = (el.text or "").strip()
            elif name == "instant":
                instant = (el.text or "").strip()
            elif name == "explicitMember":
                dims[_local(el.get("dimension", ""))] = (el.text or "").strip()
        out[ctx.get("id")] = {"start": start if end else None, "end": end or instant, "dims": dims}
    return out


def parse_instance(xml_text: str) -> list[dict]:
    """XBRL 인스턴스 → 고객 집중도 행 [{period_end, period_kind, customer, benchmark, pct, extra_dims}].

    같은 (period_end, period_kind, customer, benchmark)가 사업부 차원 등으로 여러 번 나오면 추가 차원이 적은 것을 남긴다.
    """
    root = ET.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text)
    ctxs = _contexts(root)
    best: dict[tuple, dict] = {}
    for el in root:
        if _local(el.tag) != FACT or "us-gaap" not in el.tag:
            continue
        ctx = ctxs.get(el.get("contextRef"))
        if not ctx or not ctx["end"] or el.text is None or not el.text.strip():
            continue
        dims = ctx["dims"]
        if CUSTOMER_AXIS not in dims:
            continue
        typ = dims.get(TYPE_AXIS)
        if typ and _local(typ) != "CustomerConcentrationRiskMember":
            continue
        bench = _benchmark(dims.get(BENCHMARK_AXIS))
        if not bench:
            continue
        raw = float(el.text.strip())
        if not 0 <= raw <= 1:      # XBRL pure 비율은 0~1. 그 밖이면 단위 오류라 저장하지 않는다
            continue
        cust = _local(dims[CUSTOMER_AXIS])
        cust = cust[:-6] if cust.endswith("Member") else cust
        extra = sorted((k, _local(v)) for k, v in dims.items() if k not in (CUSTOMER_AXIS, BENCHMARK_AXIS, TYPE_AXIS))
        if any(k == GEO_AXIS for k, _ in extra):   # 'X 지역 매출 중 미국계 최종 고객 비중' 같은 위치 비중 — 개별 고객 비중이 아니다
            continue
        row = {"period_end": ctx["end"], "period_kind": _period_kind(ctx["start"], ctx["end"]), "customer": cust,
               "benchmark": bench, "pct": round(raw * 100, 4),
               "extra_dims": ";".join(f"{k}={v}" for k, v in extra) or None}
        key = (row["period_end"], row["period_kind"], cust, bench)
        if key not in best or len(extra) < best[key][0]:
            best[key] = (len(extra), row)
    return [row for _, row in best.values()]


def _filings(cik: int) -> list[dict]:
    """최근 10-K 1건 + 10-Q 최근 N_10Q건, 오래된 순."""
    from pipeline.sec_filings import _get
    rec = _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", as_json=True)["filings"]["recent"]
    tenk, tenq = [], []
    for i, form in enumerate(rec["form"]):
        f = {"form": form, "accession": rec["accessionNumber"][i], "filing_date": rec["filingDate"][i]}
        if form == "10-K" and not tenk:
            tenk.append(f)
        elif form == "10-Q" and len(tenq) < N_10Q:
            tenq.append(f)
    return sorted(tenk + tenq, key=lambda f: f["filing_date"])


def _instance(cik: int, accession: str) -> str | None:
    from pipeline.sec_filings import _get
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}"
    items = _get(f"{base}/index.json", as_json=True)["directory"]["item"]
    name = next((it["name"] for it in items if it["name"].endswith("_htm.xml")), None)
    time.sleep(PAUSE)
    if not name:
        return None
    text = _get(f"{base}/{name}")
    time.sleep(PAUSE)
    return text


def collect(tickers: list[str] | None = None) -> dict:
    """티커별 최근 10-K + 10-Q 6건의 고객 집중도를 us_customer_concentration에 upsert. 한 티커 실패는 남기고 계속."""
    import config  # noqa: F401 — .env(SEC_USER_AGENT)
    from database import get_connection
    from pipeline.sec_filings import cik_map
    ciks = cik_map()
    stored, by_ticker, none, failed = 0, {}, [], []
    conn = get_connection()
    try:
        for ticker in tickers or TICKERS:
            if ticker not in ciks:
                failed.append(f"{ticker}: CIK 없음")
                continue
            try:
                n, no_instance = 0, []
                for f in _filings(ciks[ticker]):
                    xml = _instance(ciks[ticker], f["accession"])
                    if xml is None:
                        no_instance.append(f["accession"])
                        continue
                    rows = parse_instance(xml)
                    for key in {(r["period_end"], r["period_kind"], r["benchmark"]) for r in rows}:
                        conn.execute("DELETE FROM us_customer_concentration WHERE ticker=? AND period_end=? AND period_kind=? AND benchmark=?",
                                     (ticker, *key))
                    for r in rows:
                        conn.execute(
                            "INSERT INTO us_customer_concentration (ticker, period_end, period_kind, customer, benchmark, pct, extra_dims, "
                            "form, accession, fetched_at) VALUES (?,?,?,?,?,?,?,?,?, datetime('now')) "
                            "ON CONFLICT(ticker, period_end, period_kind, customer, benchmark) DO UPDATE SET pct=excluded.pct, "
                            "extra_dims=excluded.extra_dims, form=excluded.form, accession=excluded.accession, fetched_at=excluded.fetched_at",
                            (ticker, r["period_end"], r["period_kind"], r["customer"], r["benchmark"], r["pct"], r["extra_dims"],
                             f["form"], f["accession"]))
                        n += 1
                conn.commit()
                stored += n
                by_ticker[ticker] = n
                if not n:
                    none.append(ticker)
                if no_instance:
                    failed.append(f"{ticker}: XBRL 인스턴스 없음 {len(no_instance)}건")
            except Exception as e:  # noqa: BLE001
                failed.append(f"{ticker}: {type(e).__name__}: {e}")
    finally:
        conn.close()
    status = "error" if not stored else "partial" if failed else "ok"
    return {"stored": stored, "by_ticker": by_ticker, "none": none, "failed": failed, "status": status}


ANON = re.compile(r"^(Revenue|Receivable|Major)?Customer(One|Two|Three|Four|Five|[A-Z]|\d+)?$|^(Undisclosed|Largest)Customer$")
GROUP = re.compile(r"(Two|Three|Four|Five)LargestCustomers|GroupOf")


def _label(customer: str) -> str | None:
    """익명 멤버(CustomerA·RevenueCustomer5)는 None — 글자가 공시마다 같은 회사라는 보장이 없다.
    이름 공시면 낙타 표기를 띄어 쓴다(CiscoSystemsInc → Cisco Systems Inc)"""
    return None if ANON.match(customer) else re.sub(r"(?<=[a-z.])(?=[A-Z])", " ", customer)


def latest(conn, ticker: str) -> dict | None:
    """매출 기준 고객 집중도 — 가장 최근 기간(Q·FY 중 끝 날짜가 늦은 것)의 고객 비중과, 분기별 최대 고객 비중 추이(최근 6분기)"""
    rows = conn.execute("SELECT period_end, period_kind, customer, pct FROM us_customer_concentration "
                        "WHERE ticker=? AND benchmark='revenue' AND period_kind IN ('Q','FY') AND pct IS NOT NULL "
                        "ORDER BY period_end DESC", (ticker,)).fetchall()
    if not rows:
        return None
    end, kind = rows[0]["period_end"], rows[0]["period_kind"]
    # 묶음 행(INTC ThreeLargestCustomers 43%)은 개별 고객이 아니라 빼고 — 더하면 중복이다
    rows = [r for r in rows if not GROUP.search(r["customer"])]
    if not rows:
        return None
    cur = sorted([r for r in rows if r["period_end"] == end and r["period_kind"] == kind], key=lambda r: -r["pct"])
    top: dict[str, float] = {}
    for r in rows:
        if r["period_kind"] == "Q":
            top[r["period_end"]] = max(top.get(r["period_end"], 0), r["pct"])
    trend = [{"period_end": p, "top_pct": round(top[p], 1)} for p in sorted(top)[-6:]]
    return {"period_end": end, "period_kind": kind,
            "customers": [{"label": _label(r["customer"]), "pct": round(r["pct"], 1)} for r in cur], "top_trend": trend}
