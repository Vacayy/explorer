"""대만 → 한국 연결표 (docs/specs/tw-revenue.md §6) — 대만 월매출을 한국 종목 해석으로 잇는다 (LLM 0).

관계 유형:
- peer(동종): 같은 업황을 먼저 보여 준다
- demand(고객 수요): 내 물건을 사 가는 쪽의 매출
- capex(설비 투자): 고객이 설비를 늘리는가의 대리 지표
연결 자체는 투자 판단이라 사람이 확정한다(status: draft → confirmed). 여기 값은 2026-10-18 초안이다.

근거(evidence): 대만 연결 회사들의 분기 매출 합 YoY와 한국 종목의 분기 매출 YoY를 시차 0·1·2분기로 비교한다
(대만이 앞선다고 가정). 겹치는 분기가 10개 안팎이라 '맞다'의 증명이 아니라 어긋나는 연결을 걸러내는 장치다.
"""
from __future__ import annotations

import math

# (한국 코드, 한국 이름, 관계, [대만 코드], 이유)
LINKS = [
    ("000660", "SK하이닉스", "demand", ["2382", "6669", "2317"], "AI 서버 ODM 매출 = HBM·서버 DRAM 수요"),
    ("000660", "SK하이닉스", "peer", ["2408", "2344"], "대만 DRAM 업체 = 범용 메모리 업황·가격"),
    ("005930", "삼성전자", "peer", ["2408", "2344", "2337"], "대만 메모리 업체 = DRAM·NAND 업황"),
    ("005930", "삼성전자", "peer", ["2330", "2303"], "대만 파운드리 = 파운드리 업황"),
    ("067310", "하나마이크론", "peer", ["3711", "6239", "8150"], "대만 후공정(OSAT) = 메모리 패키징 업황"),
    ("131970", "두산테스나", "peer", ["2449", "6257"], "대만 테스트 하우스 = 테스트 업황"),
    ("095340", "ISC", "peer", ["6515", "6510"], "대만 테스트 소켓·프로브 = AI 칩 테스트 소켓 수요"),
    ("252990", "샘씨엔에스", "demand", ["6223", "6510"], "프로브카드 업체 매출 = 프로브카드용 세라믹 기판(STF) 수요"),
    ("031980", "피에스케이홀딩스", "capex", ["3131", "3583", "3711"], "첨단 패키징 습식 장비·OSAT = 첨단 패키징 설비 투자"),
    ("240810", "원익IPS", "capex", ["3131", "6196", "2404"], "대만 팹 장비·시공 = 파운드리 설비 투자(간접 — 주 고객은 국내 메모리)"),
    ("089970", "브이엠", "peer", ["2408", "2344"], "메모리 업황(간접 — 주 고객 SK하이닉스 설비 투자)"),
]
# 대만 밸류체인과 이을 근거가 약해 두는 것: 가온전선·두산에너빌리티·SK텔레콤·삼양식품·에이피알·실리콘투·
# 한화에어로스페이스·현대로템·SGC에너지·미래에셋증권·제이에스링크

LAGS = (0, 1, 2)
REVENUE_ACCOUNTS = ("매출액", "매출", "수익(매출액)", "영업수익")


def _tw_quarters(conn, codes: list[str]) -> dict[str, float]:
    """대만 연결 회사들의 분기 매출 합 YoY(%) — 3개월이 다 있는 분기만"""
    ph = ",".join("?" * len(codes))
    rows = conn.execute(f"SELECT ym, SUM(revenue) r, SUM(last_year) ly, COUNT(*) n FROM tw_monthly_revenue "
                        f"WHERE code IN ({ph}) GROUP BY ym", codes).fetchall()
    q: dict[str, list] = {}
    for r in rows:
        if r["n"] < len(codes) or not r["ly"]:
            continue
        y, m = int(r["ym"][:4]), int(r["ym"][5:])
        key = f"{y % 100:02d}.{((m - 1) // 3 + 1) * 3:02d}"      # 한국 재무 기간 표기(23.03·23.06…)와 맞춘다
        q.setdefault(key, []).append((r["r"], r["ly"]))
    return {k: round((sum(a for a, _ in v) / sum(b for _, b in v) - 1) * 100, 1) for k, v in q.items() if len(v) == 3}


def _kr_quarters(stock_code: str) -> dict[str, float]:
    """한국 종목 분기 매출 YoY(%) — dart_service 조회 경로(CFS 우선, Q4=연간−(Q1~Q3), D-183) 재사용"""
    from database import get_connection
    from services.dart_service import _build_financial_response
    conn = get_connection()
    try:
        row = conn.execute("SELECT corp_code FROM companies WHERE stock_code=?", (stock_code,)).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    vals: dict[str, float] = {}
    for fs in ("CFS", "OFS"):              # 연결 우선, 연결이 없거나 비면 별도 (프로젝트 규칙)
        r = _build_financial_response(row["corp_code"], "IS", "quarterly", 2022, 2026, fs)
        rev = next((x for x in r.get("rows", []) if x.get("account_nm") in REVENUE_ACCOUNTS), None)
        got = {p: float(v) for p, v in zip(r.get("periods", []), rev["values"]) if v not in (None, "", "-")} if rev else {}
        if len(got) > len(vals):
            vals = got
        if len(vals) >= 8:
            break
    out = {}
    for p, v in vals.items():
        prev = f"{int(p[:2]) - 1:02d}{p[2:]}"
        if prev in vals and vals[prev]:
            out[p] = round((v / vals[prev] - 1) * 100, 1)
    return out


def _shift(period: str, quarters: int) -> str:
    y, m = int(period[:2]), int(period[3:])
    idx = y * 4 + (m // 3 - 1) - quarters
    return f"{idx // 4:02d}.{(idx % 4 + 1) * 3:02d}"


def _corr(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 4:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 2)


def evidence(tw: dict[str, float], kr: dict[str, float]) -> dict:
    """시차별 상관과 같은 방향 비율. lag=k는 대만 k분기 전 YoY와 한국 이번 분기 YoY를 짝짓는다"""
    out = {}
    for lag in LAGS:
        pairs = [(tw[_shift(p, lag)], v) for p, v in sorted(kr.items()) if _shift(p, lag) in tw]
        same = sum(1 for a, b in pairs if (a >= 0) == (b >= 0))
        out[lag] = {"n": len(pairs), "corr": _corr([a for a, _ in pairs], [b for _, b in pairs]),
                    "same_dir": round(same / len(pairs), 2) if pairs else None}
    best = max((lag for lag in LAGS if out[lag]["corr"] is not None), key=lambda k: out[k]["corr"], default=None)
    return {"by_lag": out, "best_lag": best}


def evaluate_all() -> list[dict]:
    from database import get_connection
    conn = get_connection()
    try:
        results = []
        for kr_code, kr_name, rel, tw_codes, why in LINKS:
            tw = _tw_quarters(conn, tw_codes)
            kr = _kr_quarters(kr_code)
            results.append({"kr_code": kr_code, "kr_name": kr_name, "relation": rel, "tw_codes": tw_codes, "reason": why,
                            "tw_latest": max(tw.items()) if tw else None, **evidence(tw, kr)})
        return results
    finally:
        conn.close()
