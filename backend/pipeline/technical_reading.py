"""기술적 읽기 층 (docs/specs/technical-reading.md, D-198): 스캔 결과를 계열별 평서문 5개와 '그릴 구조' 하나로 번역한다.

모델 호출 없음. 문장은 판정 값을 서술만 하고 방향·추천 어휘를 쓰지 않는다. 문장마다 값을 준 조건 id를 basis로 남긴다.
"""
from __future__ import annotations

GROUPS = [
    ("가격 구조", "주요 가격대에서 어떻게 반응하는가"),
    ("시세동향", "가격·거래량이 극값인가"),
    ("지표신호", "이동평균·지표가 어디에 있는가"),
    ("추세·모멘텀", "나타난 방향성이 이어지고 있는가"),
    ("평균회귀", "기준에서 얼마나 멀어졌는가"),
]
UNAVAILABLE = "시세 이력이 부족해 평가하지 못했습니다."


def _pct(value: float | None, signed: bool = True, digits: int = 1) -> str:
    if value is None:
        return "-"
    text = f"{value:+.{digits}f}%" if signed else f"{value:.{digits}f}%"
    return text


def _num(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.2f}"


def _short_date(day: str | None) -> str:
    return day[5:].replace("-", "/") if day and len(day) == 10 else (day or "")


def _index(scan: dict) -> tuple[dict, dict, set]:
    states = {e["id"]: e for e in scan.get("states", [])}
    signals = {e["id"]: e for e in scan.get("signals", []) if e["status"] == "pass"}
    unavailable = {e["id"] for e in scan.get("unavailable", [])}
    return states, signals, unavailable


def _passed(states: dict, identifier: str) -> dict | None:
    entry = states.get(identifier)
    return entry if entry and entry["status"] == "pass" else None


def _value(states: dict, identifier: str) -> float | None:
    entry = states.get(identifier)
    return entry["value"] if entry and entry["status"] != "unavailable" else None


def _evidence(states: dict, identifier: str) -> dict:
    entry = states.get(identifier)
    return (entry or {}).get("evidence") or {}


def _signal_list(signals: dict, order: list[str], limit: int = 3) -> tuple[list[str], list[str]]:
    texts, basis = [], []
    for identifier in order:
        entry = signals.get(identifier)
        if entry and len(texts) < limit:
            texts.append(f"{entry['label']}({_short_date(entry['date'])})")
            basis.append(identifier)
    return texts, basis


def _structure(scan: dict, states: dict, signals: dict, unavailable: set) -> tuple[str, list[str]]:
    parts, basis = [], []
    box = _passed(states, "trading_range")
    if box:
        parts.append(f"고점과 저점이 수평인 박스권 안에 있습니다(상단 {_num(box['value'])} · 하단 {_num(box['reference'])})")
        basis.append("trading_range")
    if _passed(states, "higher_lows"):
        parts.append("저점이 계단처럼 높아지고 있습니다")
        basis.append("higher_lows")
    if _passed(states, "lower_highs"):
        parts.append("고점이 차례로 낮아지고 있습니다")
        basis.append("lower_highs")
    structure_ids = [e["id"] for e in scan.get("signals", []) if e["category"] == "가격 구조"]
    events, event_basis = _signal_list(signals, structure_ids)
    if events:
        parts.append(f"최근 {scan['within']}거래일 안 구조 신호: {', '.join(events)}")
        basis.extend(event_basis)
    if not parts:
        if {"higher_lows", "lower_highs", "trading_range"} <= unavailable:
            return UNAVAILABLE, []
        return f"박스권·저점 높이기·고점 낮추기 어느 상태도 아니고, 최근 {scan['within']}거래일 안 구조 신호가 없습니다.", []
    return ". ".join(parts) + ".", basis


def _price_action(scan: dict, signals: dict, price: dict) -> tuple[str, list[str]]:
    # 5일 극값은 잦아서 읽기에서 뺀다(패널의 '잦은 신호'에 남는다).
    order = ["high_52w", "low_52w", "high_ytd", "low_ytd", "high_20d", "low_20d", "opening_gap_up", "opening_gap_down", "opening_gap_3pct", "volume_high_5d"]
    events, basis = _signal_list(signals, order)
    tail = []
    if price.get("volume_vs_20d_avg") is not None:
        tail.append(f"기준일 거래량은 20일 평균의 {price['volume_vs_20d_avg']:.1f}배")
        basis.append("price.volume_vs_20d_avg")
    if price.get("from_52w_high_pct") is not None:
        tail.append(f"52주 고점 대비 {_pct(price['from_52w_high_pct'])}")
        basis.append("price.from_52w_high_pct")
    head = f"최근 {scan['within']}거래일 안 극값 신호: {', '.join(events)}" if events else f"최근 {scan['within']}거래일 안 신고가·신저가·갭 신호가 없습니다"
    return ". ".join([head] + tail) + ".", basis


def _indicators(scan: dict, states: dict, signals: dict, unavailable: set) -> tuple[str, list[str]]:
    parts, basis = [], []
    if _passed(states, "sma_bullish_order"):
        parts.append("단기·중기·장기 이동평균이 정배열(5 > 20 > 60)입니다")
        basis.append("sma_bullish_order")
    elif _passed(states, "sma_bearish_order"):
        parts.append("단기·중기·장기 이동평균이 역배열(5 < 20 < 60)입니다")
        basis.append("sma_bearish_order")
    elif "sma_bullish_order" in unavailable:
        return UNAVAILABLE, []
    else:
        parts.append("이동평균은 정배열도 역배열도 아닌 엉킨 구간입니다")
        basis.extend(["sma_bullish_order", "sma_bearish_order"])
    order = ["golden_cross_20_60", "dead_cross_20_60", "golden_cross_5_20", "dead_cross_5_20", "macd_zero_cross", "trend_reversal_confirmed", "sma_slope_up_20d", "sma_slope_down_20d"]
    events, event_basis = _signal_list(signals, order)
    if events:
        parts.append(f"최근 {scan['within']}거래일 안 교차·반전: {', '.join(events)}")
        basis.extend(event_basis)
    else:
        parts.append(f"최근 {scan['within']}거래일 안 이동평균 교차나 반전 신호는 없습니다")
    return ". ".join(parts) + ".", basis


def _trend(states: dict, unavailable: set) -> tuple[str, list[str]]:
    parts, basis = [], []
    momentum = _value(states, "momentum_up")
    if momentum is not None:
        parts.append(f"1년 수익률(최근 1개월 제외) {_pct(momentum)}로 {'양(+)' if momentum >= 0 else '음(−)'}")
        basis.append("momentum_up" if momentum >= 0 else "momentum_down")
    above = states.get("close_above_sma")
    if above and above["status"] != "unavailable" and above["reference"]:
        distance = (above["value"] / above["reference"] - 1) * 100
        parts.append(f"200일선 {'위' if distance > 0 else '아래'}({_pct(distance)})")
        basis.append("close_above_sma" if distance > 0 else "close_below_sma")
    adx = _value(states, "adx_strong_trend")
    if adx is not None:
        strength = "강합니다" if adx >= 25 else "약해 방향보다 횡보에 가깝습니다" if adx < 20 else "보통입니다"
        evidence = _evidence(states, "adx_strong_trend")
        plus, minus = evidence.get("plus_di"), evidence.get("minus_di")
        side = ""
        if plus is not None and minus is not None and abs(plus - minus) >= 1:
            side = f"(방향 지표는 {'상승(+DI)' if plus > minus else '하락(−DI)'} 쪽이 우세)"
        parts.append(f"추세 강도 ADX {adx:.0f}은 {strength}{side}")
        basis.append("adx_strong_trend" if adx >= 25 else "adx_weak_trend")
    if not parts:
        return UNAVAILABLE, []
    return ". ".join(parts) + ".", basis


def _reversion(states: dict, signals: dict, unavailable: set) -> tuple[str, list[str]]:
    parts, basis = [], []
    disparity = _value(states, "disparity_low")
    if disparity is not None:
        parts.append(f"20일선 대비 {_pct(disparity - 100)}")
        basis.append("disparity_low" if disparity < 100 else "disparity_high")
    rsi = _value(states, "rsi_oversold")
    if rsi is not None:
        zone = "과매도 구간" if rsi <= 30 else "과매수 구간" if rsi >= 70 else "과열도 과매도도 아닙니다"
        parts.append(f"RSI {rsi:.0f}로 {zone}")
        basis.append("rsi_oversold" if rsi <= 30 else "rsi_overbought" if rsi >= 70 else "rsi_oversold")
    band = _evidence(states, "bollinger_below_lower")
    if band.get("percent_b") is not None:
        b = band["percent_b"]
        where = "하단 밖" if b < 0 else "상단 밖" if b > 1 else "안"
        parts.append(f"볼린저 밴드 {where}(%B {b:.2f})")
        basis.append("bollinger_below_lower" if b <= 1 else "bollinger_above_upper")
    if _passed(states, "bollinger_squeeze"):
        parts.append("밴드폭은 비교 구간 최소(스퀴즈)")
        basis.append("bollinger_squeeze")
    events, event_basis = _signal_list(signals, ["rsi_exit_oversold", "rsi_exit_overbought", "bollinger_reenter_lower", "bollinger_reenter_upper"], limit=2)
    if events:
        parts.append(f"최근 복귀 신호: {', '.join(events)}")
        basis.extend(event_basis)
    if not parts:
        return UNAVAILABLE, []
    return ". ".join(parts) + ".", basis


def readings(scan: dict, price: dict | None = None) -> list[dict]:
    """계열 5개마다 문장 하나. 값이 없는 계열은 이력 부족 문장."""
    price = price or {}
    states, signals, unavailable = _index(scan)
    builders = {
        "가격 구조": lambda: _structure(scan, states, signals, unavailable),
        "시세동향": lambda: _price_action(scan, signals, price),
        "지표신호": lambda: _indicators(scan, states, signals, unavailable),
        "추세·모멘텀": lambda: _trend(states, unavailable),
        "평균회귀": lambda: _reversion(states, signals, unavailable),
    }
    out = []
    for group, question in GROUPS:
        text, basis = builders[group]()
        seen, unique = set(), []
        for identifier in basis:
            if identifier not in seen:
                seen.add(identifier); unique.append(identifier)
        out.append({"group": group, "question": question, "text": text, "basis": unique})
    return out


def canvas(scan: dict) -> dict:
    """스캔 결과로 '먼저 그릴 구조'를 고른다. 첫 규칙이 맞으면 채택. 스윙 폭 5·두 점 연결 고정."""
    states, signals, _ = _index(scan)
    pick = lambda kind, window, reason, basis: {"kind": kind, "window": window, "swing": 5, "fit": "two_point", "reason": reason, "basis": basis}  # noqa: E731
    if _passed(states, "trading_range"):
        return pick("levels", "6m", "고점·저점이 수평인 박스권이라 지지·저항 레벨을 그립니다", ["trading_range"])
    for identifier in ("channel_break_up", "channel_break_down"):
        if identifier in signals:
            return pick("channel", "6m", f"최근 {signals[identifier]['label']} 신호가 있어 채널을 그립니다", [identifier])
    for identifier in ("higher_lows", "trendline_support_hold", "trendline_break_down"):
        if _passed(states, identifier) or identifier in signals:
            return pick("trendline_low", "6m", "저점이 높아지거나 상승 추세선 신호가 있어 저점 추세선을 그립니다", [identifier])
    for identifier in ("lower_highs", "trendline_break_up"):
        if _passed(states, identifier) or identifier in signals:
            return pick("trendline_high", "6m", "고점이 낮아지거나 하락 추세선 신호가 있어 고점 추세선을 그립니다", [identifier])
    for identifier in ("resistance_break", "support_break", "breakout_retest_rebreak", "false_breakout_up", "false_breakdown"):
        if identifier in signals:
            return pick("levels", "1y", f"최근 {signals[identifier]['label']} 신호가 있어 전고점·전저점 레벨을 그립니다", [identifier])
    for identifier in ("volume_profile_up_60d", "volume_profile_down_60d"):
        if identifier in signals:
            return pick("profile", "6m", f"최근 {signals[identifier]['label']} 신호가 있어 매물대를 그립니다", [identifier])
    return pick("levels", "1y", "성립한 구조 상태가 없어 1년 지지·저항 레벨을 기본으로 그립니다", [])
