"""대만 → 한국 연결표 (docs/specs/tw-revenue.md §6) — 대만 월매출을 한국 종목 해석으로 잇는다 (LLM 0).

관계 유형:
- peer(동종): 같은 업황을 먼저 보여 준다
- demand(고객 수요): 내 물건을 사 가는 쪽의 매출
- capex(설비 투자): 고객이 설비를 늘리는가의 대리 지표
연결은 2026-10-18 확정(사용자 승인 + 사업 구조 조사). 바꾸려면 LINKS를 고친다.

근거(evidence): 대만 연결 회사들의 분기 매출 합 YoY와 한국 종목의 분기 매출 YoY를 시차 0·1·2분기로 비교한다
(대만이 앞선다고 가정). 겹치는 분기가 10개 안팎이라 '맞다'의 증명이 아니라 어긋나는 연결을 걸러내는 장치다.
"""
from __future__ import annotations

import math

# (한국 코드, 한국 이름, 관계, [대만 코드], 이유, 사업 근거 확신도 상|중|중하)
# 2026-10-18 확정: 사업 구조(제품·고객)가 확인된 것만, 확신도 '중하' 이상. 숫자 근거는 evidence()가 따로 계산해 같이 보인다.
LINKS = [
    ("005930", "삼성전자", "peer", ["2408", "2344", "2337"], "대만 메모리 업체 = DRAM·NAND 업황", "상"),
    ("005930", "삼성전자", "peer", ["2330", "2303"], "대만 파운드리 = 파운드리 업황", "중"),
    ("000660", "SK하이닉스", "peer", ["2408", "2344"], "대만 DRAM 업체 = 범용 메모리 업황·가격", "상"),
    ("000660", "SK하이닉스", "demand", ["2382", "6669", "2317"], "AI 서버 ODM 매출 = HBM·서버 DRAM 수요", "중"),
    ("009150", "삼성전기", "peer", ["3037", "3189", "8046"], "FC-BGA 기판 동종(회사 전체 매출이라 숫자 근거는 희석)", "상"),
    ("009150", "삼성전기", "peer", ["2327"], "MLCC 동종 — AI 서버·전장 MLCC", "상"),
    ("067310", "하나마이크론", "peer", ["3711", "6239", "8150"], "대만 후공정(OSAT) = 메모리 패키징 업황", "상"),
    ("036540", "SFA반도체", "peer", ["6239", "8150"], "메모리 후공정 외주 동종(삼성 외주 비중 77%)", "중하"),
    ("095340", "ISC", "peer", ["6515", "6510"], "테스트 소켓·프로브 동종 = AI 칩 테스트 소켓 수요", "중"),
    ("252990", "샘씨엔에스", "demand", ["6223", "6510"], "프로브카드 업체 매출 = 프로브카드용 세라믹 기판(STF) 수요", "중하"),
    ("031980", "피에스케이홀딩스", "capex", ["2330", "3711"], "리플로우 장비 = TSMC CoWoS·ASE 패키징 증설(디스컴은 한국 HBM 투자)", "중"),
    ("098460", "고영", "capex", ["2317", "2382", "3231", "6669"], "ODM SMT 라인 증설 = SPI·AOI 검사장비 발주(월매출은 출하라 간접)", "중"),
    ("323280", "태성", "capex", ["4958", "3037", "3189"], "기판 업체 증설 = 습식 장비 수주(젠딩은 직접 고객)", "중"),
    ("046970", "우리로", "peer", ["3081", "4979", "3163"], "데이터센터 광소자 동종(고객은 중국 광모듈 업체)", "중하"),
    ("042700", "한미반도체", "capex", ["2330"], "CoWoS 증설은 HBM 수요의 동행 지표(실제 대만 노출은 추적 밖인 마이크론 대만 팹)", "중하"),
]
# 확신도 '하'라 넣지 않은 후보(사업상 접점은 있으나 약함): 멜콘(TSMC 공급사 등록 초기), 롯데에너지머티리얼즈(HVLP 동박 → 대만 CCL,
# 아직 전지박 위주), 오킨스전자·에이팩트(고객이 한국 IDM), 네오셈(파이슨, SSD 세대), 코세스(ASE 비중 미공개), 효성중공업·가온전선(델타와
# 데이터센터 전력 투자를 공유할 뿐 고객 관계 아님).
# 대만 연결이 틀린 것(2026-10-18 조사): 원익IPS·브이엠(국내 메모리 설비 투자 단일 변수), 두산테스나(삼성 파운드리 가동률),
# 엑시콘·디아이(삼성·SK하이닉스 메모리 투자), 주성엔지니어링(중국·한국 투자).

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
        for kr_code, kr_name, rel, tw_codes, why, conf in LINKS:
            tw = _tw_quarters(conn, tw_codes)
            kr = _kr_quarters(kr_code)
            results.append({"kr_code": kr_code, "kr_name": kr_name, "relation": rel, "tw_codes": tw_codes, "reason": why,
                            "confidence": conf,
                            "tw_latest": max(tw.items()) if tw else None, **evidence(tw, kr)})
        return results
    finally:
        conn.close()


# ── 이번 달 신호 + 화면용 읽기 ────────────────────────────────────────────────

ACCEL_PP = 10.0          # 3개월 YoY가 3개월 전보다 이만큼(%p) 움직이면 가속·둔화
_memo: dict[tuple, dict] = {}


def tw_signal(conn, codes: list[str]) -> dict:
    """연결 회사들 합계의 월별 YoY와 3개월 YoY, 3개월 전 대비 상태(가속·둔화·전환·유지)"""
    ph = ",".join("?" * len(codes))
    rows = conn.execute(f"SELECT ym, SUM(revenue) r, SUM(last_year) ly, COUNT(*) n FROM tw_monthly_revenue "
                        f"WHERE code IN ({ph}) GROUP BY ym ORDER BY ym", codes).fetchall()
    months = [(r["ym"], r["r"], r["ly"]) for r in rows if r["n"] == len(codes) and r["ly"]]
    yoy = [(ym, round((r / ly - 1) * 100, 1)) for ym, r, ly in months]

    def yoy3(i):
        if i < 2:
            return None
        win = months[i - 2:i + 1]
        return round((sum(m[1] for m in win) / sum(m[2] for m in win) - 1) * 100, 1)

    now = yoy3(len(months) - 1) if months else None
    prev = yoy3(len(months) - 4) if len(months) >= 6 else None
    state = None
    if now is not None and prev is not None:
        if prev < 0 <= now:
            state = "전환↑"
        elif prev >= 0 > now:
            state = "전환↓"
        elif now - prev >= ACCEL_PP:
            state = "가속"
        elif now - prev <= -ACCEL_PP:
            state = "둔화"
        else:
            state = "유지"
    return {"ym": months[-1][0] if months else None, "yoy": yoy[-1][1] if yoy else None, "yoy_3m": now,
            "yoy_3m_prev": prev, "state": state, "series": [{"ym": ym, "yoy": v} for ym, v in yoy[-24:]]}


def read_links(kr_code: str | None = None) -> dict:
    """연결별 이번 달 대만 신호 + 숫자 근거(시차별 상관). 대만 수집 시각이 같으면 메모리 캐시"""
    from database import get_connection
    from pipeline.tw_universe import COMPANIES
    names = {c: n for c, n, *_ in COMPANIES}
    conn = get_connection()
    try:
        stamp = conn.execute("SELECT MAX(ym), MAX(fetched_at) FROM tw_monthly_revenue").fetchone()
        items = []
        for kr, kr_name, rel, tw_codes, why, conf in LINKS:
            if kr_code and kr != kr_code:
                continue
            key = (tuple(stamp), kr, tuple(tw_codes))
            if key not in _memo:
                ev = evidence(_tw_quarters(conn, tw_codes), _kr_quarters(kr))
                _memo[key] = {"signal": tw_signal(conn, tw_codes), "evidence": ev}
            m = _memo[key]
            best = m["evidence"]["best_lag"]
            items.append({"kr_code": kr, "kr_name": kr_name, "relation": rel, "confidence": conf, "reason": why,
                          "tw": [{"code": c, "name": names.get(c, c)} for c in tw_codes], **m["signal"],
                          "evidence": {"best_lag": best, **(m["evidence"]["by_lag"][best] if best is not None else
                                                            {"n": max(v["n"] for v in m["evidence"]["by_lag"].values()), "corr": None, "same_dir": None})}})
        return {"as_of": stamp[0], "items": items}
    finally:
        conn.close()
