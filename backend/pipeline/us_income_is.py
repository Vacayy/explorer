"""미국 분기 손익계산서 수집 — Sankey '분기 손익 흐름'용 (ia-redesign §4.13 '분기 손익 흐름').

us_fundamentals와 같은 원천(SEC XBRL companyfacts)·같은 분기 분해 로직(pipeline/us_fundamentals.quarterly)을
쓰고, 저장은 **기존 us_quarterly 테이블을 재사용**한다(새 metric 이름들). 범위는 us_quarterly에 이미 들어 있는
티커만 — 백필은 백로그.

세그먼트(사업부 매출) 자동 수집은 이 PR에 포함하지 않는다: companyfacts.json은 XBRL dimension을 담지 않아
`StatementBusinessSegmentsAxis`를 돌려주지 않는다. 이 뒤의 선택지((a) raw XBRL 파싱 (b) EX-99.1 LLM 추출)는
별도 PR 백로그다. 응답의 segments 필드는 비어 있다(§6 "없으면 사업부 열을 생략").
"""
from __future__ import annotations

# metric → us-gaap 후보 태그 (처음이 가장 선호, 못 찾으면 다음으로 떨어진다)
# 매출(revenue)은 us_fundamentals.TAGS가 이미 담당하므로 여기서 중복 선언하지 않는다
IS_TAGS: dict[str, list[str]] = {
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "rnd": ["ResearchAndDevelopmentExpense"],
    "sga": ["SellingGeneralAndAdministrativeExpense",
            "GeneralAndAdministrativeExpense"],   # SG&A를 General만 보고하는 회사 대비
    "op_income": ["OperatingIncomeLoss"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"],
    "tax": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss"],
}
USE_KEY = "income_flow"


def _pick_tag(gaap: dict, candidates: list[str]) -> tuple[str, list[dict]] | None:
    """후보 중 가장 최신까지 보고된 계정. us_fundamentals._pick_tag와 같은 규칙이지만
    로컬에서 metric 이름 대신 후보 리스트를 바로 받는다."""
    best = None
    for tag in candidates:
        units = gaap.get(tag, {}).get("units", {}).get("USD")
        if units:
            key = (max(u["end"] for u in units), len(units))
            if best is None or key > best[0]:
                best = (key, tag, units)
    return (best[1], best[2]) if best else None


def collect_us_income(tickers: list[str] | None = None) -> dict:
    """SEC companyfacts에서 분기 IS 라인을 받아 us_quarterly에 upsert.

    tickers 생략 시 us_quarterly에 이미 있는 티커 전부. 한 티커 실패는 남기고 계속."""
    import config  # noqa: F401 — .env(SEC_USER_AGENT)
    from database import get_connection
    from pipeline.sec_filings import _get, cik_map
    from pipeline.us_fundamentals import quarterly

    ciks = cik_map()
    conn = get_connection()
    try:
        if tickers is None:
            tickers = [r["ticker"] for r in conn.execute(
                "SELECT DISTINCT ticker FROM us_quarterly ORDER BY ticker").fetchall()]
        stored, failed = 0, []
        for ticker in tickers:
            cik = ciks.get(ticker)
            if cik is None:
                failed.append(f"{ticker}: CIK 없음")
                continue
            try:
                facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", as_json=True)
                gaap = facts.get("facts", {}).get("us-gaap", {})
            except Exception as e:  # noqa: BLE001
                failed.append(f"{ticker}: {type(e).__name__}")
                continue
            for metric, candidates in IS_TAGS.items():
                picked = _pick_tag(gaap, candidates)
                if not picked:
                    failed.append(f"{ticker}: {metric} 계정 없음")
                    continue
                tag, units = picked
                qv = quarterly(units)
                for q, v in qv.items():
                    conn.execute(
                        "INSERT INTO us_quarterly (ticker, q, metric, value, tag, use_key, fetched_at) "
                        "VALUES (?,?,?,?,?,?, datetime('now')) "
                        "ON CONFLICT(ticker, q, metric) DO UPDATE SET value=excluded.value, tag=excluded.tag, "
                        "use_key=excluded.use_key, fetched_at=excluded.fetched_at",
                        (ticker, q, metric, v, tag, USE_KEY),
                    )
                    stored += 1
                conn.commit()
    finally:
        conn.close()
    return {"stored": stored, "failed": failed,
            "status": "error" if not stored else "partial" if failed else "ok"}
