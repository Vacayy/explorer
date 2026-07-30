"""기술적 위치 계산 — '좋은 기업과 좋은 주식은 다르다' (LLM 0).

펀더멘탈 재료만으로는 과열/과매도를 못 본다 — RSI·이평선·52주 위치·
멀티플 역사 밴드로 '주가의 위치'를 브리프 재료에 공급한다.
밴드는 장기 평균회귀의 준거: 성장주는 절대 싸지지 않는다는 공식도 있지만
어느 정도의 밴드는 존재한다 (stakeholder 관점, 2026-07-13).
"""
from database import get_connection


def _closes(conn, stock_code: str, n: int = 130, table: str = "stock_prices") -> list[dict]:
    rows = conn.execute(f"""
        SELECT trade_date, close, high FROM {table}
        WHERE stock_code=? AND close IS NOT NULL
        ORDER BY trade_date DESC LIMIT ?""", (stock_code, n)).fetchall()
    return [dict(r) for r in rows][::-1]  # 과거 → 최신


def _rsi14(closes: list[int]) -> float | None:
    if len(closes) < 15:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    # Wilder smoothing
    ag = sum(gains[:14]) / 14
    al = sum(losses[:14]) / 14
    for g, l in zip(gains[14:], losses[14:]):
        ag = (ag * 13 + g) / 14
        al = (al * 13 + l) / 14
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 1)


def compute_technicals(conn, stock_code: str, table: str = "stock_prices") -> dict | None:
    rows = _closes(conn, stock_code, table=table)
    if len(rows) < 21:
        return None
    closes = [r["close"] for r in rows]
    cur = closes[-1]

    def ma_gap(n):
        if len(closes) < n:
            return None
        ma = sum(closes[-n:]) / n
        return round((cur - ma) / ma * 100, 1)

    high_52w = conn.execute(f"""
        SELECT max(high) h FROM {table}
        WHERE stock_code=? AND trade_date >= date('now', '-365 days')""",
        (stock_code,)).fetchone()["h"]
    return {
        "rsi14": _rsi14(closes),
        "ma20_gap": ma_gap(20), "ma60_gap": ma_gap(60), "ma120_gap": ma_gap(120),
        "off_52w_high": round((cur - high_52w) / high_52w * 100, 1) if high_52w else None,
        "ret_1m": round((cur - closes[-21]) / closes[-21] * 100, 1) if len(closes) >= 21 else None,
        "ret_3m": round((cur - closes[-63]) / closes[-63] * 100, 1) if len(closes) >= 63 else None,
    }


def per_band(conn, stock_code: str, years: int = 4) -> dict | None:
    """멀티플 역사 밴드 — 연간 EPS × 그 해 주가 범위로 trailing PER 밴드 근사.

    fwd PER 이력이 쌓이기 전까지의 평균회귀 준거. EPS<=0인 해는 제외.
    """
    eps_rows = conn.execute("""
        SELECT fs.bsns_year y, MAX(fs.thstrm_amount) ni
        FROM financial_statements fs JOIN companies c ON c.corp_code = fs.corp_code
        WHERE c.stock_code=? AND fs.reprt_code='11011' AND fs.sj_div IN ('IS','CIS')
          AND fs.account_nm LIKE '당기순이익%' AND fs.account_nm NOT LIKE '%지배%'
        GROUP BY fs.bsns_year
        ORDER BY fs.bsns_year DESC LIMIT ?""", (stock_code, years)).fetchall()
    shares = conn.execute("""
        SELECT shares FROM stock_prices WHERE stock_code=? AND shares IS NOT NULL
        ORDER BY trade_date DESC LIMIT 1""", (stock_code,)).fetchone()
    if not eps_rows or not shares or not shares["shares"]:
        return None
    n_shares = shares["shares"]
    pers = []
    for r in eps_rows:
        try:
            ni = int(r["ni"])
        except (TypeError, ValueError):
            continue
        if ni <= 0:
            continue
        eps = ni / n_shares
        px = conn.execute("""
            SELECT min(close) lo, max(close) hi FROM stock_prices
            WHERE stock_code=? AND trade_date BETWEEN ? AND ?""",
            (stock_code, f"{r['y']}-01-01", f"{r['y']}-12-31")).fetchone()
        if not px or not px["lo"]:
            continue
        pers.append({"year": r["y"], "lo": round(px["lo"] / eps, 1), "hi": round(px["hi"] / eps, 1)})
    if not pers:
        return None
    band = {"bands": pers,
            "min": min(p["lo"] for p in pers), "max": max(p["hi"] for p in pers)}
    # 현재 trailing PER과 밴드 내 위치 (0=하단, 1=상단) — 임계점 판정용
    cur_px = conn.execute("""
        SELECT close FROM stock_prices WHERE stock_code=? AND close IS NOT NULL
        ORDER BY trade_date DESC LIMIT 1""", (stock_code,)).fetchone()
    latest = eps_rows[0]
    try:
        eps = int(latest["ni"]) / n_shares
        if cur_px and eps > 0:
            band["current_per"] = round(cur_px["close"] / eps, 1)
            if band["max"] > band["min"]:
                band["position"] = round((band["current_per"] - band["min"]) / (band["max"] - band["min"]), 2)
    except (TypeError, ValueError):
        pass
    return band


def at_threshold(technicals: dict | None, band: dict | None) -> str | None:
    """임계점 상태 판정 — 브리프의 '돌파의 조건' 섹션 발동 여부.

    반환: 임계점 서술 문자열 (없으면 None). 임계점 = 전례없는 구간의 문턱:
    52주 고점 5% 이내(신고가권) 또는 trailing PER이 역사 밴드 80%+ 위치.
    """
    reasons = []
    if technicals and technicals.get("off_52w_high") is not None and technicals["off_52w_high"] >= -5:
        reasons.append(f"52주 고점 대비 {technicals['off_52w_high']:+}% — 신고가권")
    if band and band.get("position") is not None and band["position"] >= 0.8:
        if band["position"] >= 1:
            desc = f"역사 밴드({band['min']}~{band['max']}배) 상단을 넘어선 전례없는 구간"
        else:
            desc = f"역사 밴드({band['min']}~{band['max']}배) 상단 근접 (위치 {round(band['position']*100)}%)"
        reasons.append(f"trailing PER {band.get('current_per')}배 — {desc}")
    return " · ".join(reasons) if reasons else None


def volume_by_price(conn, stock_code: str, window: int = 250, bins: int = 20,
                    table: str = "stock_prices") -> dict | None:
    """매물대 — 최근 window 거래일의 가격대별 거래량 프로파일 (LLM 0, 추세 렌즈 원칙 3).

    가격 구간별 거래량 히스토그램 → POC(최대 거래 가격대) + 현재가 위 저항 물량 / 아래 지지 물량 비중.
    데이터 부족(<40행) 또는 가격 무변동이면 None.
    """
    rows = conn.execute(f"""
        SELECT close, volume FROM {table}
        WHERE stock_code=? AND close IS NOT NULL AND volume IS NOT NULL
        ORDER BY trade_date DESC LIMIT ?""", (stock_code, window)).fetchall()
    if len(rows) < 40:
        return None
    closes = [r["close"] for r in rows]
    vols = [r["volume"] or 0 for r in rows]
    cur = closes[0]  # 최신
    lo, hi = min(closes), max(closes)
    if hi <= lo:
        return None
    width = (hi - lo) / bins
    buckets = [0.0] * bins
    for c, v in zip(closes, vols):
        idx = min(int((c - lo) / width), bins - 1)
        buckets[idx] += v
    total = sum(buckets) or 1
    poc_idx = max(range(bins), key=lambda i: buckets[i])
    poc_price = lo + (poc_idx + 0.5) * width
    cur_idx = min(int((cur - lo) / width), bins - 1)
    overhead = sum(buckets[cur_idx + 1:]) / total * 100   # 현재가 위 = 저항
    support = sum(buckets[:cur_idx]) / total * 100          # 현재가 아래 = 지지
    top = sorted(range(bins), key=lambda i: buckets[i], reverse=True)[:3]
    nodes = [{"price": round(lo + (i + 0.5) * width), "vol_pct": round(buckets[i] / total * 100, 1)}
             for i in sorted(top)]
    return {"cur": round(cur), "poc": round(poc_price),
            "poc_vs_cur": "above" if poc_price > cur else "below",
            "overhead_pct": round(overhead, 1), "support_pct": round(support, 1),
            "nodes": nodes, "lo": round(lo), "hi": round(hi), "window": len(rows)}
