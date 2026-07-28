"""시장 국면 (market regime, D-076, docs/specs/market-regime.md).

매크로 리스크 포스처 — 3중 필터(감성 오실레이터 × 20EMA 추세 게이트 × 변동성)를
하나의 비중 포스처로 **결정적 결합(LLM 0)**. 미국=글로벌 리스크 날씨, 국장=매매 본판.

- 지표 = fact (F&G·VIX·S&P·KOSPI·VKOSPI). hypothesis 아님.
- 포스처·근거 = frame (규칙 기반 템플릿, 검증된 지식 아님).
- 저장 = market_indicators 일별 스냅샷(원지표만). 파생(EMA·RSI·vol·기울기)은 읽을 때 계산.

fetch 실패는 부분(degraded)으로 흡수 — 국장 추세(KOSPI)만 있어도 국장 포스처는 나온다.
"""
from datetime import datetime, timedelta

import pandas as pd

from database import get_connection

# 브라우저 UA — CNN F&G는 무헤더 시 418 봇차단 (feasibility 실측 2026-07-28)
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# 원지표 (스냅샷 저장 대상). 파생(EMA·RSI·vol·기울기)은 읽을 때 계산.
# kospi = 국장 오실레이터(RSI14) 계산 입력. sp500 미저장 — 추세 게이트는 오실레이터의 EMA라 지수 불요.
RAW_INDICATORS = ("fear_greed", "vix", "kospi", "vkospi")


# ──────────────────────────── fetch ────────────────────────────

def _yf_history(ticker: str, days: int = 90) -> list[tuple[str, float]]:
    """yfinance 종가 히스토리 → [(YYYY-MM-DD, close)]. 마지막 봉 NaN 가능 → dropna."""
    import yfinance as yf
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    h = yf.Ticker(ticker).history(start=start)["Close"].dropna()
    return [(idx.strftime("%Y-%m-%d"), round(float(v), 2)) for idx, v in h.items()]


def _fear_greed_history(days: int = 90) -> list[tuple[str, float]]:
    """CNN Fear & Greed — 현재+히스토리. 브라우저 UA 필수. 비공식 API라 실패 허용."""
    import requests
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    r = requests.get(
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        headers={"User-Agent": _UA, "Accept": "application/json", "Referer": "https://edition.cnn.com/"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json().get("fear_and_greed_historical", {}).get("data", [])
    out = []
    for pt in data:
        d = datetime.utcfromtimestamp(pt["x"] / 1000).strftime("%Y-%m-%d")
        if d >= cutoff:
            out.append((d, round(float(pt["y"]), 1)))
    return out


def _vkospi_history(days: int = 90) -> list[tuple[str, float]]:
    """VKOSPI — naver 차트 API. 심볼 미확정이면 빈 배열 → 호출측이 실현변동성 폴백."""
    import requests
    for sym in ("VKOSPI", "KOSPI_VKOSPI"):
        try:
            r = requests.get(
                f"https://api.stock.naver.com/chart/domestic/index/{sym}",
                params={"periodType": "dayCandle", "count": days},
                headers={"User-Agent": _UA, "Referer": "https://m.stock.naver.com"},
                timeout=10,
            )
            js = r.json()
            rows = js if isinstance(js, list) else js.get("priceInfos") or js.get("data") or []
            out = []
            for row in rows:
                d = str(row.get("localDate") or row.get("date") or "")
                d = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d
                v = row.get("closePrice") or row.get("close")
                if d and v is not None:
                    out.append((d, round(float(v), 2)))
            if out:
                return out
        except Exception:
            continue
    return []


def _kospi_realized_vol(kospi: list[tuple[str, float]], window: int = 20) -> list[tuple[str, float]]:
    """KOSPI 20일 실현변동성(연율화 %) — VKOSPI 폴백. 항상 계산 가능."""
    if len(kospi) < window + 1:
        return []
    import numpy as np
    s = pd.Series([v for _, v in kospi], index=[d for d, _ in kospi])
    logret = np.log(s / s.shift(1))
    vol = logret.rolling(window).std() * np.sqrt(252) * 100
    return [(d, round(float(v), 2)) for d, v in vol.dropna().items()]


# ──────────────────────────── snapshot ────────────────────────────

def snapshot_market() -> dict:
    """전 지표 히스토리를 fetch → market_indicators에 멱등 적재(INSERT OR REPLACE).

    첫 실행 시 트레일링 히스토리를 통째로 넣어 스파크라인이 즉시 채워짐.
    각 소스 실패는 개별 흡수 — 얻은 것만 저장, 실패는 degraded로 보고.
    """
    fetched: dict[str, list[tuple[str, float]]] = {}
    degraded: list[str] = []

    def _try(name: str, fn):
        try:
            rows = fn()
            if rows:
                fetched[name] = rows
            else:
                degraded.append(name)
        except Exception as e:
            degraded.append(f"{name}({type(e).__name__})")

    _try("fear_greed", _fear_greed_history)
    _try("vix", lambda: _yf_history("^VIX"))
    _try("kospi", lambda: _yf_history("^KS11"))   # 국장 오실레이터(RSI14) 입력
    _try("vkospi", _vkospi_history)

    # VKOSPI 폴백 — 실현변동성을 kospi_vol로 저장 (국장 변동성 축 보장)
    if "vkospi" not in fetched and "kospi" in fetched:
        vol = _kospi_realized_vol(fetched["kospi"])
        if vol:
            fetched["kospi_vol"] = vol

    conn = get_connection()
    n = 0
    for indicator, rows in fetched.items():
        for d, v in rows:
            conn.execute(
                "INSERT OR REPLACE INTO market_indicators(snapshot_date, indicator, value) VALUES (?,?,?)",
                (d, indicator, v),
            )
            n += 1
    conn.commit()
    conn.close()
    return {"rows": n, "indicators": list(fetched.keys()), "degraded": degraded}


# ──────────────────────────── posture (LLM 0) ────────────────────────────

def _series(conn, indicator: str, limit: int = 70) -> list[tuple[str, float]]:
    rows = conn.execute(
        "SELECT snapshot_date, value FROM market_indicators WHERE indicator=? "
        "ORDER BY snapshot_date DESC LIMIT ?",
        (indicator, limit),
    ).fetchall()
    return [(r["snapshot_date"], r["value"]) for r in reversed(rows)]


def _ema_of(dated: list[tuple[str, float]], span: int = 20) -> list[tuple[str, float]]:
    """**오실레이터의 20 EMA** (F&G·RSI 위에 얹는 추세선, 태린이 아빠 규율의 핵심).

    가격 EMA가 아니다 — 감성 오실레이터 자체를 평활한 값. 기울기가 추세 게이트.
    """
    if len(dated) < span:
        return []
    ema = pd.Series([v for _, v in dated]).ewm(span=span, adjust=False).mean()
    return [(dated[i][0], round(float(ema.iloc[i]), 2)) for i in range(len(dated))]


def _osc_slope(ema: list[tuple[str, float]], look: int = 5, eps: float = 1.0) -> tuple[float | None, str]:
    """오실레이터 EMA의 최근 look일 기울기 → up/flat/down. 0~100 스케일이라 절대 포인트(±eps)."""
    if not ema:
        return None, "unknown"
    last = ema[-1][1]
    if len(ema) <= look:
        return last, "unknown"
    delta = last - ema[-1 - look][1]
    return last, ("up" if delta > eps else "down" if delta < -eps else "flat")


def _rsi14_series(dated: list[tuple[str, float]], period: int = 14) -> list[tuple[str, float]]:
    """KOSPI 종가 → RSI14 시계열 (국장 오실레이터 — 직접 F&G 부재의 모멘텀 프록시)."""
    if len(dated) < period + 1:
        return []
    s = pd.Series([v for _, v in dated])
    delta = s.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi = 100 - 100 / (1 + rs)
    return [(dated[i][0], round(float(rsi.iloc[i]), 1))
            for i in range(len(dated)) if pd.notna(rsi.iloc[i])]


def _fg_zone(score: float) -> str:
    return ("extreme_fear" if score < 25 else "fear" if score < 45
            else "neutral" if score <= 55 else "greed" if score <= 75 else "extreme_greed")


def _band(value: float, low: float, high: float) -> str:
    return "calm" if value < low else "elevated" if value <= high else "stress"


def _posture(oversold: bool, overbought: bool, trend: str, vol_stress: bool) -> tuple[str, str, str]:
    """(포스처 라벨, 색, 근거) — 결정적 매트릭스.

    색 키는 신호등 시맨틱(favorable/caution/risk/neutral) — 가격 방향(상승=빨강)과 무관.
    """
    if oversold and trend in ("up", "flat"):
        label, color, reason = "비중 확대 구간", "favorable", "공포 + 오실레이터 EMA 지지 → 분할 매수 유효"
    elif oversold and trend == "down":
        label, color, reason = "보류", "caution", "과매도지만 오실레이터 20EMA 우하향 → 반등은 속임수 경계, EMA 눕기 대기"
    elif overbought and trend == "up":
        label, color, reason = "과열 경계", "caution", "추세는 살아있으나 탐욕권 → 신규 비중 자제"
    elif overbought and trend == "down":
        label, color, reason = "축소", "risk", "탐욕 + 추세 이탈 → 비중 축소"
    else:
        label, color, reason = "중립", "neutral", "뚜렷한 엣지 없음"
    if vol_stress:
        reason += " · 변동성 높음(사이징 축소)"
    return label, color, reason


def get_regime() -> dict:
    """저장된 스냅샷에서 양 시장 포스처 + 스파크라인 series 계산. LLM 0.

    추세 게이트 = **오실레이터의 20 EMA 기울기**(가격 EMA 아님). 오실레이터가 바닥에서
    반등해도 EMA가 우하향이면 '보류' — 반등이 속임수일 수 있으니 EMA 눕기 대기.
    """
    conn = get_connection()
    ser = {ind: _series(conn, ind) for ind in (*RAW_INDICATORS, "kospi_vol")}
    conn.close()

    degraded = [ind for ind in RAW_INDICATORS if not ser[ind]]
    as_of = max((s[-1][0] for s in ser.values() if s), default=None)

    # ── 미국 (날씨): F&G 오실레이터 + 그 20 EMA(추세 게이트) × VIX ──
    us = None
    if ser["fear_greed"] or ser["vix"]:
        fg = ser["fear_greed"][-1][1] if ser["fear_greed"] else None
        vix = ser["vix"][-1][1] if ser["vix"] else None
        fg_ema = _ema_of(ser["fear_greed"])
        ema_last, ema_dir = _osc_slope(fg_ema)
        oversold = fg is not None and fg < 25
        overbought = fg is not None and fg > 75
        vol_stress = vix is not None and vix > 30
        label, color, reason = _posture(oversold, overbought, ema_dir, vol_stress)
        us = {
            "posture": label, "posture_color": color, "reason": reason,
            "fear_greed": {"score": fg, "zone": _fg_zone(fg)} if fg is not None else None,
            "vix": {"value": vix, "band": _band(vix, 20, 30)} if vix is not None else None,
            "trend": {"ema": ema_last, "dir": ema_dir},   # F&G의 20 EMA
            "series": {"osc": ser["fear_greed"], "osc_ema": fg_ema, "vix": ser["vix"]},
        }

    # ── 국장 (본판): RSI14 오실레이터 + 그 20 EMA(추세 게이트) × VKOSPI/실현변동성 ──
    kr = None
    if ser["kospi"]:
        rsi_ser = _rsi14_series(ser["kospi"])
        rsi = rsi_ser[-1][1] if rsi_ser else None
        rsi_ema = _ema_of(rsi_ser)
        ema_last, ema_dir = _osc_slope(rsi_ema)
        vkospi = ser["vkospi"][-1][1] if ser["vkospi"] else None
        vol = vkospi if vkospi is not None else (ser["kospi_vol"][-1][1] if ser["kospi_vol"] else None)
        vol_label = "VKOSPI" if vkospi is not None else "실현변동성"
        oversold = rsi is not None and rsi < 30
        overbought = rsi is not None and rsi > 70
        vol_stress = vol is not None and vol > 25
        label, color, reason = _posture(oversold, overbought, ema_dir, vol_stress)
        kr = {
            "posture": label, "posture_color": color, "reason": reason,
            "oscillator": {"metric": "RSI14", "value": rsi,
                           "zone": "oversold" if oversold else "overbought" if overbought else "neutral"},
            "trend": {"ema": ema_last, "dir": ema_dir},   # RSI14의 20 EMA
            "volatility": {"metric": vol_label, "value": vol,
                           "band": _band(vol, 15, 25)} if vol is not None else None,
            "series": {"osc": rsi_ser, "osc_ema": rsi_ema, "vol": ser["vkospi"] or ser["kospi_vol"]},
        }

    # BLUF: 국장 포스처가 헤드라인, 미국은 날씨 맥락
    headline = kr["reason"] if kr else (us["reason"] if us else "시장 데이터 수집 대기")

    return {"as_of": as_of, "headline": headline, "kr": kr, "us": us, "degraded": degraded}
