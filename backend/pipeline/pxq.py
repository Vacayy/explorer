"""P×Q 분해 — 한국 수출(금액·중량)으로 사이클의 성격을 가른다 (docs/specs/value-chain.md §10, LLM 0).

3개월 합 기준: 금액 YoY = (1 + 단가 YoY) × (1 + 물량 YoY) − 1. 단가 P = 금액/kg, 물량 Q = kg.
기여도는 로그로 나눈다: ln(1+gV) = ln(1+gP) + ln(1+gQ).
- 가격 주도: 금액과 같은 방향에서 단가 기여가 물량 기여의 2배 이상
- 물량 주도: 반대로 물량 기여가 단가의 2배 이상
- 동반: 둘 다 같은 방향이고 어느 쪽도 2배를 넘지 않음
- 역행: 단가와 물량이 반대 방향(예: 단가↑ 물량↓ — 공급 부족·구성 고급화, 단가↓ 물량↑ — 밀어내기)
칩은 kg이 비트·개수를 대표하지 못한다(HBM 비중이 늘면 kg당 단가가 오른다) → '단가'가 아니라 '단가·구성' 효과로 읽는다.
"""
from __future__ import annotations

import math


def _yoy3(series: dict[str, float], p: str) -> float | None:
    y, m = int(p[:4]), int(p[5:])
    months = [f"{(y * 12 + m - 1 - k) // 12}-{(y * 12 + m - 1 - k) % 12 + 1:02d}" for k in range(3)]
    prev = [f"{int(x[:4]) - 1}{x[4:]}" for x in months]
    if not all(x in series for x in months + prev):
        return None
    a, b = sum(series[x] for x in months), sum(series[x] for x in prev)
    return a / b - 1 if b else None


FLAT = 0.03   # ±3% 안의 변화는 0으로 본다(단가 −2%를 '역행'이라 부르지 않게)


def classify(gp: float, gq: float) -> str:
    if abs(gp) < FLAT and abs(gq) < FLAT:
        return "정체"
    if abs(gp) < FLAT:
        return "물량 주도"
    if abs(gq) < FLAT:
        return "가격 주도"
    lp, lq = math.log1p(gp), math.log1p(gq)
    if lp * lq < 0:
        return "역행"
    if abs(lp) >= 2 * abs(lq):
        return "가격 주도"
    if abs(lq) >= 2 * abs(lp):
        return "물량 주도"
    return "동반"


def decompose(conn, hs: str) -> dict | None:
    """최신 달의 3개월 YoY 금액·물량·단가와 판정, 최근 12개월 추이"""
    rows = conn.execute("SELECT period, export_usd, export_wt FROM trade_stats WHERE hs_code=? AND export_usd > 0 "
                        "AND export_wt > 0 ORDER BY period", (hs,)).fetchall()
    if not rows:
        return None
    usd = {r["period"]: r["export_usd"] for r in rows}
    wt = {r["period"]: r["export_wt"] for r in rows}
    hist = []
    for p in sorted(usd):
        gv, gq = _yoy3(usd, p), _yoy3(wt, p)
        if gv is None or gq is None or gq <= -1:
            continue
        gp = (1 + gv) / (1 + gq) - 1
        lv = math.log1p(gv)
        hist.append({"period": p, "value_yoy": round(gv * 100, 1), "qty_yoy": round(gq * 100, 1), "price_yoy": round(gp * 100, 1),
                     "price_share": round(math.log1p(gp) / lv * 100) if abs(lv) > 1e-9 else None, "verdict": classify(gp, gq)})
    if not hist:
        return None
    return {"hs": hs, **hist[-1], "history": hist[-12:]}
