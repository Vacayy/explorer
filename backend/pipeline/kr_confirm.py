"""한국 확인 신호 (docs/specs/value-chain.md §4) — 대만 신호를 한국 쪽 원천 두 개로 교차 확인한다 (LLM 0·네트워크 0).

종목마다 세 원천의 방향을 나란히 놓는다.
1. 대만: 연결된 대만 회사 합계의 3개월 YoY와 상태(pipeline/tw_links)
2. 수출: 그 종목에 맞는 HS 품목(HS_MAP) 수출액의 3개월 YoY와 상태(trade_stats, 관세청 월간)
3. 공시: 최근 90일 단일판매·공급계약 공시 수(직전 90일 대비)·180일 신규시설투자·마지막 잠정실적(disclosures)
세 원천이 같은 방향이면 강한 신호, 하나만이면 약한 신호로 읽는다. 매출 전망이 아니다.
"""
from __future__ import annotations

from datetime import date, timedelta

ACCEL_PP = 10.0

# 종목 → [(HS 코드, 관계 direct|demand, 설명, 확신도)] — 2026-10-18 조사(근거·출처는 스펙 §4 표).
# 세 원천 일치 집계에는 확신도 상·중만 센다. '하'는 참고로만 보인다(포괄 코드이거나 회사 매출이 해외 법인이라 한국 통계에 안 잡힘).
HS_MAP: dict[str, list[tuple[str, str, str, str]]] = {
    "005930": [("854232", "direct", "메모리반도체 수출(삼성·SK하이닉스 합산)", "상"),
               ("854231", "direct", "시스템반도체 수출(다른 팹리스·재수출 섞임)", "중")],
    "000660": [("8542323000", "direct", "HBM 수출", "상"),
               ("854232", "direct", "메모리반도체 수출(삼성·SK하이닉스 합산)", "상")],
    "009150": [("8532240000", "direct", "MLCC 수출(해외 공장 물량 제외)", "상"),
               ("8542900000", "direct", "집적회로 부분품 — FC-BGA(커패시터 실장 기판, CBP N325811)·리드프레임 섞임", "중")],
    "067310": [("854232", "demand", "메모리 수출 업황 — 후공정은 자기 HS가 없고 매출 상당 부분이 베트남 법인", "하")],
    "036540": [("854232", "demand", "메모리 수출 업황 — 후공정은 자기 HS가 없고 필리핀 법인 이전", "하")],
    "095340": [("8536691000", "direct", "IC 테스트 소켓(업계 단위, 러버 소켓은 8536.90으로 갈 수 있음)", "하")],
    "252990": [("9030901000", "demand", "프로브카드 등 반도체 검사기 부분품(업황 대리)", "하")],
    "031980": [("8486402093", "direct", "웨이퍼 범핑용 기기 — 리플로우(범핑 도금 등 섞임)", "중")],
    "042700": [("8486402010", "direct", "다이 부착기·와이어 본더 — TC 본더(한화세미텍 등 섞임, 월별 등락 큼)", "중")],
    "098460": [("9031499000", "direct", "광학식 검사기기 기타 — SPI·AOI(포괄 코드)", "중"),
               ("9031419000", "direct", "반도체 검사기기 — 패키지 검사", "중")],
    "323280": [("8534009000", "demand", "PCB·기판 수출(장비 자체는 넓은 8479.89라 직접 신호 없음)", "하")],
    "046970": [("8541499000", "direct", "감광성 반도체 디바이스 기타 — 패키징된 APD·PIN(광커플러 등 섞임)", "하"),
               ("8541491000", "direct", "포토다이오드 칩", "하")],
}
COUNTED = ("상", "중")


def _state(now: float | None, prev: float | None) -> str | None:
    if now is None or prev is None:
        return None
    if prev < 0 <= now:
        return "전환↑"
    if prev >= 0 > now:
        return "전환↓"
    if now - prev >= ACCEL_PP:
        return "가속"
    if now - prev <= -ACCEL_PP:
        return "둔화"
    return "유지"


def trade_signal(conn, hs: str) -> dict:
    """품목 수출액(USD)의 3개월 YoY — 같은 달 전년과 3개월 합을 비교"""
    rows = {r["period"]: r["export_usd"] for r in conn.execute(
        "SELECT period, export_usd FROM trade_stats WHERE hs_code=? AND export_usd IS NOT NULL ORDER BY period", (hs,))}
    periods = sorted(rows)

    def yoy3(i):
        if i < 2:
            return None
        cur = periods[i - 2:i + 1]
        prev = [f"{int(p[:4]) - 1}{p[4:]}" for p in cur]
        if any(p not in rows for p in prev) or not sum(rows[p] for p in prev):
            return None
        return round((sum(rows[p] for p in cur) / sum(rows[p] for p in prev) - 1) * 100, 1)

    now = yoy3(len(periods) - 1) if periods else None
    prev = yoy3(len(periods) - 4) if len(periods) >= 4 else None
    return {"hs": hs, "period": periods[-1] if periods else None, "yoy_3m": now, "yoy_3m_prev": prev, "state": _state(now, prev)}


def disclosure_signal(conn, stock_code: str, today: date | None = None) -> dict:
    """공급계약 공시 수(최근 90일 vs 직전 90일), 180일 신규시설투자, 마지막 잠정실적"""
    today = today or date.today()
    d = lambda days: (today - timedelta(days=days)).strftime("%Y%m%d")  # noqa: E731
    base = ("SELECT d.rcept_dt, TRIM(d.report_nm) nm, d.dart_url FROM disclosures d JOIN companies c ON c.corp_code=d.corp_code "
            "WHERE c.stock_code=? AND d.rcept_dt>=? AND d.rcept_dt<? ")
    contracts = lambda a, b: conn.execute(base + "AND d.report_nm LIKE '%공급계약%' AND d.report_nm NOT LIKE '%해지%' "  # noqa: E731
                                          "ORDER BY d.rcept_dt DESC", (stock_code, d(a), d(b))).fetchall()
    recent, prior = contracts(90, -1), contracts(180, 90)
    capex = conn.execute(base + "AND d.report_nm LIKE '%신규시설투자%'", (stock_code, d(180), d(-1))).fetchall()
    prelim = conn.execute(base + "AND d.report_nm LIKE '%영업(잠정)실적%' ORDER BY d.rcept_dt DESC LIMIT 1",
                          (stock_code, d(400), d(-1))).fetchone()
    up = len(recent) > len(prior) or bool(capex)
    return {"contracts_90d": len(recent), "contracts_prev_90d": len(prior), "capex_180d": len(capex),
            "last_contract": recent[0]["rcept_dt"] if recent else None,
            "last_prelim": {"date": prelim["rcept_dt"], "title": prelim["nm"], "url": prelim["dart_url"]} if prelim else None,
            "direction": "up" if up else ("down" if len(recent) < len(prior) else "flat")}


def _dir(state: str | None, yoy: float | None) -> str | None:
    """상태 → 방향(up/down/flat). 상태가 없으면 YoY 부호로"""
    if state in ("가속", "전환↑"):
        return "up"
    if state in ("둔화", "전환↓"):
        return "down"
    if state == "유지":
        return "flat" if yoy is None else ("up" if yoy > 0 else "down")
    return None


def confirm(stock_code: str) -> dict:
    """세 원천 방향과 일치 수 — 대만 신호는 연결이 여럿이면 사업 근거가 가장 높은 연결을 대표로"""
    from database import get_connection
    from pipeline.tw_links import read_links
    links = read_links(stock_code)["items"]
    rank = {"상": 0, "중": 1, "중하": 2}
    main = sorted(links, key=lambda l: rank.get(l["confidence"], 9))[0] if links else None
    conn = get_connection()
    try:
        trades = [{**trade_signal(conn, hs), "relation": rel, "note": note, "confidence": conf}
                  for hs, rel, note, conf in HS_MAP.get(stock_code, [])]
        disc = disclosure_signal(conn, stock_code)
    finally:
        conn.close()
    tw_dir = _dir(main["state"], main["yoy_3m"]) if main else None
    trade_main = next((t for t in trades if t["yoy_3m"] is not None and t["confidence"] in COUNTED), None)
    tr_dir = _dir(trade_main["state"], trade_main["yoy_3m"]) if trade_main else None
    dirs = [x for x in (tw_dir, tr_dir, disc["direction"]) if x]
    return {"stock_code": stock_code, "taiwan": main, "trade": trades, "disclosure": disc,
            "trade_counted": trade_main["hs"] if trade_main else None,
            "directions": {"taiwan": tw_dir, "trade": tr_dir, "disclosure": disc["direction"]},
            "agree_up": sum(1 for x in dirs if x == "up"), "observed": len(dirs)}
