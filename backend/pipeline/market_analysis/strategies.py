"""Versioned, deterministic screening formulas. No IO and no database access.

The catalog describes Explorer's definitions, not an undocumented HTS vendor's
implementation. All trailing windows exclude future bars. Ratios use percentage
points; insufficient/invalid input is unavailable, never a negative match.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
import math
from numbers import Real
from typing import Any

CATALOG_VERSION = "explorer-strategies-v1"
_ENTRIES: dict[str, dict[str, Any]] = {}
_KINDS: dict[str, str] = {}


def _integer(label: str, minimum: int = 1, maximum: int = 250) -> dict:
    return {"type": "integer", "label": label, "min": minimum, "max": maximum, "step": 1}


def _number(label: str, minimum: float = 0, maximum: float = 100) -> dict:
    return {"type": "number", "label": label, "min": minimum, "max": maximum, "step": 0.1}


def _choice(label: str, options: list[str]) -> dict:
    return {"type": "string", "label": label, "options": options}


def _add(identifier: str, label: str, category: str, kind: str, formula: str,
         defaults: dict | None = None, parameters: dict | None = None,
         required: tuple[str, ...] = ("close",), timeframe: str = "1d",
         description: str | None = None, available: bool = True) -> None:
    _ENTRIES[identifier] = {
        "id": identifier, "label": label, "category": category,
        "timeframe": timeframe, "description": description or formula,
        "defaults": defaults or {}, "parameters": parameters or {},
        "required_data": list(required), "available": available, "formula": formula,
    }
    _KINDS[identifier] = kind


def _build_catalog() -> None:
    price, signal, rank = "시세동향", "지표신호", "순위종목"
    _add("price_flat", "보합", price, "flat", "abs(종가 / 전일 종가 - 1) × 100 ≤ 허용률",
         {"tolerance_pct": 0}, {"tolerance_pct": _number("보합 허용률 (%)", 0, 10)})
    for period in (20, 5):
        for direction, name, field in (("high", "신고가", "high"), ("low", "신저가", "low")):
            _add(f"{direction}_{period}d", f"{period}일 {name} 갱신", price, direction,
                 f"당일 기준가격이 직전 기간의 {field} 극값을 엄격히 {'초과' if field == 'high' else '하회'} (당일 제외)",
                 {"period": period, "price_field": field},
                 {"period": _integer("비교 기간 (영업일)"), "price_field": _choice("당일 기준가격", [field, "close"])},
                 (field, "close"))
        if period == 20:
            _add("opening_gap_3pct", "3% 시가갭 발생", price, "gap_abs",
                 "abs(시가 / 전일 종가 - 1) × 100 ≥ 기준률",
                 {"threshold_pct": 3}, {"threshold_pct": _number("갭 기준률 (%)", 0.1, 100)}, ("open", "close"))
    _add("volume_high_5d", "5일 최고거래량 갱신", price, "volume_high",
         "당일 거래량 > 직전 기간의 최대 거래량 (당일 제외)", {"period": 5},
         {"period": _integer("비교 기간 (영업일)")}, ("volume",))
    for direction, label, field in (("up", "상승", "high"), ("down", "하락", "low")):
        _add(f"opening_gap_{direction}", f"시가 {label}갭", price, f"gap_{direction}",
             f"시가 {'>' if direction == 'up' else '<'} 전일 {'고가' if field == 'high' else '저가'}",
             required=("open", field))
    for span, title in (("52w", "52주"), ("ytd", "연중(1월 이후)")):
        for direction, label, field in (("high", "신고가", "high"), ("low", "신저가", "low")):
            _add(f"{direction}_{span}", f"{title}{label}", price, f"{direction}_{span}",
                 f"당일 기준가격이 {'직전 365일' if span == '52w' else '해당 연도 1월 1일 이후'} {field} 극값을 엄격히 {'초과' if direction == 'high' else '하회'} (당일 제외)",
                 {"price_field": field}, {"price_field": _choice("당일 기준가격", [field, "close"])}, (field, "close"))
    _add("volume_increase", "전일대비 거래량 증가", price, "volume_increase",
         "(거래량 / 전일 거래량 - 1) × 100 > 최소 증가율", {"min_increase_pct": 0},
         {"min_increase_pct": _number("최소 증가율 (%)", 0, 10000)}, ("volume",))
    _add("near_high_10d", "10일 신고가 1%이내 근접", price, "near_high",
         "직전 기간의 최고가 × (1 - 근접률 / 100) ≤ 종가 ≤ 직전 기간의 최고가",
         {"period": 10, "distance_pct": 1}, {"period": _integer("비교 기간 (영업일)"), "distance_pct": _number("근접률 (%)", 0, 50)}, ("close", "high"))
    _add("breakout_pullback_10d", "10일 신고가돌파후 1%이탈", price, "breakout_pullback",
         "최근 돌파 탐색기간 내 종가가 직전 기간 최고가를 돌파한 뒤, 그 돌파 기준가격의 하단 이탈률 선을 종가가 하향 교차",
         {"period": 10, "breakout_lookback": 10, "drop_pct": 1},
         {"period": _integer("신고가 기간 (영업일)"), "breakout_lookback": _integer("돌파 탐색기간 (영업일)"), "drop_pct": _number("하단 이탈률 (%)", 0, 50)}, ("close", "high"),
         description="Explorer 정의: 최신 돌파의 고정 기준가격보다 1% 낮은 선을 종가가 하향 돌파. 돌파 다음 봉부터 검사합니다.")
    for direction, label in (("surge", "급등"), ("drop", "급락")):
        _add(f"price_{direction}_10m", f"가격 {label}(10분봉)", price, f"intraday_{direction}",
             "연속된 같은 거래일 10분봉의 종가 변동률이 상승/하락 기준률 이상",
             {"threshold_pct": 3}, {"threshold_pct": _number("변동 기준률 (%)", 0.1, 100)}, ("timestamp", "close"), "10m", available=False,
             description="실제 10분봉 필요. 현재 일봉 스냅샷에서는 평가할 수 없습니다.")
    _add("volume_spike_10m", "거래량 급증(10분봉)", price, "intraday_volume",
         "당일 현재 10분봉 거래량 / 같은 거래일 직전 연속 N개 10분봉 평균 거래량 ≥ 배수",
         {"period": 5, "multiple": 2}, {"period": _integer("비교 봉 수", 1, 36), "multiple": _number("평균 대비 배수", 1, 100)},
         ("timestamp", "volume"), "10m", available=False,
         description="실제 10분봉 필요. 당일 연속된 비교 봉이 부족하면 미평가합니다.")
    for period in (20, 60):
        for direction, label in (("up", "상향"), ("down", "하향")):
            _add(f"volume_profile_{direction}_{period}d", f"{period}일 매물대 {label}돌파", signal, f"profile_{direction}",
                 "직전 N일 대표가격 (고가+저가+종가)/3 에 일 거래량을 배정한 동일 폭 가격구간 중 최대 거래량 구간의 중심선을 종가가 교차 (추정)",
                 {"period": period, "bins": 20}, {"period": _integer("매물대 기간 (영업일)", 2), "bins": _integer("가격 구간 수", 2, 100)},
                 ("high", "low", "close", "volume"), description="일봉 추정 매물대입니다. 체결가별 실제 거래량이 아니며 동률이면 낮은 가격구간을 선택합니다.")
        if period == 20:
            for ma_period in (20, 5):
                for kind, direction, label in (("slope", "up", "상승반전"), ("cross", "up", "상향돌파"), ("slope", "down", "하락반전"), ("cross", "down", "하향돌파")):
                    _add(f"sma_{kind}_{direction}_{ma_period}d", f"{ma_period}일 이평 {label}", signal, f"sma_{kind}_{direction}",
                         "종가 단순이평 기울기의 부호 반전" if kind == "slope" else "종가가 종가 단순이평을 교차",
                         {"period": ma_period}, {"period": _integer("이평 기간 (영업일)", 2)})
    for kind, label in (("golden", "골든"), ("dead", "데드")):
        for fast, slow in ((20, 60), (5, 20)):
            _add(f"{kind}_cross_{fast}_{slow}", f"이평 {label}크로스({fast},{slow})", signal, f"ma_{kind}",
                 f"단기 종가 단순이평이 장기 종가 단순이평을 {'상향' if kind == 'golden' else '하향'} 교차",
                 {"fast": fast, "slow": slow}, {"fast": _integer("단기 이평"), "slow": _integer("장기 이평", 2)})
    for direction, label in (("bearish", "역배열(60,20,5)"), ("bullish", "정배열(5,20,60)")):
        _add(f"sma_{direction}_order", f"이평 {label}", signal, f"order_{direction}",
             "단기 > 중기 > 장기 종가 단순이평" if direction == "bullish" else "단기 < 중기 < 장기 종가 단순이평",
             {"fast": 5, "middle": 20, "slow": 60}, {"fast": _integer("단기 이평"), "middle": _integer("중기 이평", 2), "slow": _integer("장기 이평", 3)})
    _add("trend_reversal_confirmed", "추세전환 확인형", signal, "trend_reversal",
         "기준 이평 기울기가 비상승에서 상승으로 전환한 뒤 확인기간 동안 기울기 > 0 이고 종가 > 이평 유지; 마지막 확인봉에서 발생",
         {"period": 20, "confirmation": 3}, {"period": _integer("기준 이평 기간", 2), "confirmation": _integer("확인 봉 수", 1, 20)},
         description="Explorer 정의: 20일 단순이평 상승반전 후 3봉 연속 종가가 이평 위에 있고 이평도 상승한 시점.")
    for family, label in (("macd", "MACD"), ("sonar", "SONAR")):
        for crossing, crossing_label in (("zero", "0선"), ("signal", "Signal")):
            defaults = {"fast": 12, "slow": 26, "signal": 9} if family == "macd" else {"period": 20, "lag": 9, "signal": 9}
            parameters = ({"fast": _integer("단기 EMA"), "slow": _integer("장기 EMA", 2)} if family == "macd" else {"period": _integer("EMA 기간"), "lag": _integer("차분 간격")})
            defaults["direction"] = "up"
            parameters.update({"signal": _integer("Signal EMA 기간"), "direction": _choice("돌파 방향", ["up", "down"])})
            formula = "MACD = EMA(종가, 단기) - EMA(종가, 장기)" if family == "macd" else "SONAR = EMA(종가, 기간) - 간격 이전 EMA(종가, 기간)"
            _add(f"{family}_{crossing}_cross", f"{label} {crossing_label} 돌파({'12,26,9' if family == 'macd' else '20,9,9'})", signal, f"{family}_{crossing}",
                 formula + f"; {'0선' if crossing == 'zero' else '지표의 Signal EMA'} 교차 (기본 상향); SMA 시드, 최소 250봉 고정 준비기간", defaults, parameters)
    for variant, title in (("slow", "slow"), ("fast", "fast")):
        defaults = {"period": 10, "d_period": 5, "oversold": 20}
        parameters = {"period": _integer("고저 범위 기간", 2), "d_period": _integer("%D 평활 기간"), "oversold": _number("과매도 기준", 0, 100)}
        if variant == "slow":
            defaults["k_period"] = 5
            parameters["k_period"] = _integer("%K 평활 기간")
        _add(f"stochastic_{variant}_buy", f"Stochastic {title} 매수({'10,5,5' if variant == 'slow' else '10,5'})", signal, f"stoch_{variant}",
             "원시 %K = 100 × (종가 - 기간 최저가) / (기간 최고가 - 기간 최저가); " + ("slow %K = SMA(원시 %K, K기간); " if variant == "slow" else "") + "%D = SMA(%K, D기간); 전일 %K와 %D가 과매도 이하이고 당일 %K가 %D를 상향 교차",
             defaults, parameters, ("high", "low", "close"),
             description="Explorer 매수 신호 정의: 과매도 영역에서 %K/%D 상향 교차. slow 파라미터는 잘린 이미지에 대해 (10,5,5)를 기본값으로 채택했습니다.")
    for identifier, label, formula, required in (
        ("volume", "거래량 상위", "당일 거래량", ("volume",)),
        ("trading_value", "거래대금 상위", "당일 실제 거래대금 (종가 × 거래량으로 대체하지 않음)", ("trading_value",)),
        ("return_20d", "20일 대비율 상위", "(당일 종가 / 20영업일 전 종가 - 1) × 100", ("close",)),
        ("volume_growth", "거래량 증가율 상위", "(당일 거래량 / 전일 거래량 - 1) × 100", ("volume",)),
        ("turnover", "당일 회전율 상위", "당일 거래량 / 같은 날짜 상장주식수 × 100", ("volume", "shares")),
        ("return_1d", "전일 대비율 상위", "(당일 종가 / 전일 종가 - 1) × 100", ("close",)),
    ):
        _add(f"rank_{identifier}", label, rank, f"rank_{identifier}", formula,
             {"top_n": 20}, {"top_n": _integer("상위 종목 수", 1, 500)}, required,
             available=identifier != "trading_value",
             description=formula + "; 일반 조건 통과 종목 중 내림차순, 동률은 종목코드 오름차순. 거래대금은 원자료가 없으면 미평가." if identifier == "trading_value" else formula + "; 일반 조건 통과 종목 중 내림차순, 동률은 종목코드 오름차순.")


_build_catalog()


def catalog() -> list[dict]:
    """Return independent JSON-serializable catalog entries in screenshot order."""
    return deepcopy(list(_ENTRIES.values()))


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def normalize_condition(condition: dict) -> dict:
    if not isinstance(condition, dict) or set(condition) - {"strategy_id", "params", "within_days"}:
        raise ValueError("strategy condition must contain strategy_id, params, within_days only")
    identifier = condition.get("strategy_id")
    if not isinstance(identifier, str) or identifier not in _ENTRIES:
        raise ValueError("unknown strategy_id")
    entry = _ENTRIES[identifier]
    supplied = condition.get("params", {})
    if not isinstance(supplied, dict) or set(supplied) - set(entry["parameters"]):
        raise ValueError(f"unknown parameters for {identifier}")
    params = {**entry["defaults"], **supplied}
    for key, value in params.items():
        schema = entry["parameters"][key]
        if schema["type"] == "string":
            if not isinstance(value, str) or value not in schema["options"]:
                raise ValueError(f"invalid {key}")
        else:
            if not _finite_number(value):
                raise ValueError(f"{key} must be a finite number")
            if schema["type"] == "integer" and (not isinstance(value, int)):
                raise ValueError(f"{key} must be an integer")
            if not schema["min"] <= value <= schema["max"]:
                raise ValueError(f"{key} out of bounds")
    if "fast" in params and not params["fast"] < params["slow"]:
        raise ValueError("fast must be less than slow")
    if "middle" in params and not params["fast"] < params["middle"] < params["slow"]:
        raise ValueError("fast < middle < slow is required")
    within = condition.get("within_days", 1)
    if isinstance(within, bool) or not isinstance(within, int) or not 1 <= within <= 250:
        raise ValueError("within_days must be an integer between 1 and 250")
    if identifier.startswith("rank_") and within != 1:
        raise ValueError("ranking strategies require within_days=1")
    if entry["timeframe"] == "10m" and within != 1:
        raise ValueError("intraday strategies currently require within_days=1 (latest completed bar)")
    return {"strategy_id": identifier, "params": params, "within_days": within}


def is_ranking(condition: dict) -> bool:
    return normalize_condition(condition)["strategy_id"].startswith("rank_")


def _base_sessions(kind: str, p: dict) -> int:
    if kind in {"high", "low", "volume_high", "near_high", "profile_up", "profile_down"}:
        return p["period"] + 1
    if kind == "breakout_pullback":
        return p["period"] + p["breakout_lookback"] + 1
    if kind.startswith("sma_slope"):
        return p["period"] + 2
    if kind.startswith("sma_cross"):
        return p["period"] + 1
    if kind in {"ma_golden", "ma_dead"}:
        return p["slow"] + 1
    if kind.startswith("order_"):
        return p["slow"]
    if kind == "trend_reversal":
        return p["period"] + p["confirmation"] + 1
    if kind.startswith("macd_"):
        # Both variants share the same fixed EMA seed span, so their MACD
        # values agree for a given date and do not depend on extra history.
        return max(250, 5 * p["slow"] + p["signal"])
    if kind.startswith("sonar_"):
        return max(250, 5 * p["period"] + p["lag"] + p["signal"])
    if kind.startswith("stoch_"):
        return p["period"] + (p.get("k_period", 1) - 1) + p["d_period"]
    if kind == "rank_return_20d":
        return 21
    if kind in {"rank_volume", "rank_trading_value", "rank_turnover"}:
        return 1
    if kind == "intraday_volume":
        return p["period"] + 1
    return 2


def history_requirement(condition: dict, as_of: str) -> dict:
    normalized = normalize_condition(condition)
    kind = _KINDS[normalized["strategy_id"]]
    end = date.fromisoformat(as_of)
    start = None
    # Calendar bounds include a conservative holiday margin when scanning past
    # sessions. Actual per-event bounds are checked again by the evaluator.
    earliest = end if normalized["within_days"] == 1 else end - timedelta(days=2 * (normalized["within_days"] - 1) + 14)
    if kind.endswith("_52w"):
        start = (earliest - timedelta(days=365)).isoformat()
    elif kind.endswith("_ytd"):
        start = date(earliest.year, 1, 1).isoformat()
    return {"sessions": _base_sessions(kind, normalized["params"]) + normalized["within_days"] - 1, "start_date": start}


def _out(status: str, value: float | None = None, reference: float | None = None,
         day: str | None = None, reason: str | None = None, **extra: Any) -> dict:
    if any(v is not None and not math.isfinite(v) for v in (value, reference)):
        return {"status": "unavailable", "value": None, "reference": None, "date": day, "reason": "invalid_numeric_result"}
    return {"status": status, "value": value, "reference": reference, "date": day, "reason": reason, **extra}


def _decision(passed: bool, value: float, reference: float, day: str, **extra: Any) -> dict:
    return _out("pass" if passed else "fail", value, reference, day, **extra)


def _sma(values: list[float | None], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        if all(value is not None for value in window):
            result[i] = math.fsum(value / period for value in window)
    return result


def _ema(values: list[float | None], period: int) -> list[float | None]:
    """SMA seed after period contiguous valid observations; reset on gaps."""
    result: list[float | None] = [None] * len(values)
    alpha, previous, run = 2 / (period + 1), None, []
    for i, value in enumerate(values):
        if value is None:
            previous, run = None, []
            continue
        if previous is None:
            run.append(value)
            if len(run) < period:
                continue
            previous = math.fsum(item / period for item in run)
        else:
            previous = alpha * value + (1 - alpha) * previous
        result[i] = previous
    return result


def _cross(previous: float, current: float, before_reference: float,
           reference: float, direction: str = "up") -> bool:
    return previous <= before_reference and current > reference if direction == "up" else previous >= before_reference and current < reference


def _equal(a: float, b: float) -> bool:
    # Arithmetic at a threshold (e.g. 101/100 -> 1%) can differ by a few ULPs.
    # Use machine-scale tolerance, not a market-price-sized relative epsilon.
    return abs(a - b) <= max(1e-12, 8 * math.ulp(a), 8 * math.ulp(b))


def _ge(a: float, b: float) -> bool:
    return a >= b or _equal(a, b)


def _le(a: float, b: float) -> bool:
    return a <= b or _equal(a, b)


def _lines(rows: list[dict], kind: str, p: dict) -> dict[str, list]:
    closes = [row.get("close") for row in rows]
    if kind.startswith("sma_") or kind == "trend_reversal":
        return {"ma": _sma(closes, p["period"])}
    if kind.startswith("ma_") or kind.startswith("order_"):
        return {key: _sma(closes, p[key]) for key in ("fast", "middle", "slow") if key in p}
    if kind.startswith("macd_"):
        fast, slow = _ema(closes, p["fast"]), _ema(closes, p["slow"])
        values = [f - s if f is not None and s is not None else None for f, s in zip(fast, slow)]
        return {"value": values, "signal": _ema(values, p["signal"])}
    if kind.startswith("sonar_"):
        base, lag = _ema(closes, p["period"]), p["lag"]
        values = [base[i] - base[i - lag] if i >= lag and base[i] is not None and base[i - lag] is not None else None for i in range(len(rows))]
        return {"value": values, "signal": _ema(values, p["signal"])}
    if kind.startswith("stoch_"):
        values: list[float | None] = [None] * len(rows)
        for i in range(p["period"] - 1, len(rows)):
            window = rows[i - p["period"] + 1:i + 1]
            high, low = max(row["high"] for row in window), min(row["low"] for row in window)
            if high > low:
                values[i] = 100 * ((rows[i]["close"] - low) / (high - low))
        k = _sma(values, p["k_period"]) if kind == "stoch_slow" else values
        return {"k": k, "d": _sma(k, p["d_period"])}
    return {}


def _at(rows: list[dict], i: int, kind: str, p: dict, lines: dict) -> dict:
    row = rows[i]
    day = row["timestamp"] if kind.startswith("intraday_") else row["date"]
    previous = rows[i - 1] if i else {}
    close = row.get("close")
    if kind == "flat":
        value = 100 * abs(close / previous["close"] - 1)
        return _decision(_le(value, p["tolerance_pct"]), value, p["tolerance_pct"], day)
    if kind.startswith("gap_"):
        if kind == "gap_abs":
            value = 100 * (row["open"] / previous["close"] - 1)
            return _decision(_ge(abs(value), p["threshold_pct"]), value, p["threshold_pct"], day)
        ref = previous["high" if kind == "gap_up" else "low"]
        return _decision(row["open"] > ref if kind == "gap_up" else row["open"] < ref, row["open"], ref, day)
    if kind in {"high", "low", "volume_high", "near_high"} or kind.endswith(("_52w", "_ytd")):
        if kind.endswith(("_52w", "_ytd")):
            when = date.fromisoformat(row["date"])
            since = when - timedelta(days=365) if kind.endswith("_52w") else date(when.year, 1, 1)
            if date.fromisoformat(rows[0]["date"]) > since:
                return _out("unavailable", day=day, reason="insufficient_history")
            prior = [item for item in rows[:i] if item["date"] >= since.isoformat()]
        else:
            prior = rows[i - p["period"]:i]
        if not prior:
            return _out("unavailable", day=day, reason="insufficient_history")
        low = kind.startswith("low")
        field = "volume" if kind == "volume_high" else "low" if low else "high"
        reference = (min if low else max)(item[field] for item in prior)
        value = row["volume"] if kind == "volume_high" else row[p.get("price_field", "close")]
        if kind == "near_high":
            return _decision(_ge(close, reference * (1 - p["distance_pct"] / 100)) and _le(close, reference), close, reference, day)
        return _decision(value < reference if low else value > reference, value, reference, day)
    if kind in {"volume_increase", "rank_volume_growth"}:
        if previous["volume"] <= 0:
            return _out("unavailable", day=day, reason="zero_reference_volume")
        value = 100 * (row["volume"] / previous["volume"] - 1)
        if kind.startswith("rank_"):
            return _out("pass", value, previous["volume"], day, ranking=True, top_n=p["top_n"])
        return _decision(value > p["min_increase_pct"] and not _equal(value, p["min_increase_pct"]), value, p["min_increase_pct"], day)
    if kind == "breakout_pullback":
        for j in range(i - 1, max(p["period"] - 1, i - p["breakout_lookback"] - 1), -1):
            level = max(item["high"] for item in rows[j - p["period"]:j])
            if rows[j]["close"] > level:
                reference = level * (1 - p["drop_pct"] / 100)
                return _decision(_cross(previous["close"], close, reference, reference, "down"), close, reference, day,
                                 evidence={"breakout_date": rows[j]["date"], "breakout_level": level})
        return _out("fail", day=day, reason="no_prior_breakout")
    if kind.startswith("profile_"):
        window = rows[i - p["period"]:i]
        typical = [math.fsum(item[key] / 3 for key in ("high", "low", "close")) for item in window]
        low, high = min(typical), max(typical)
        if math.fsum(item["volume"] for item in window) <= 0:
            return _out("unavailable", day=day, reason="zero_reference_volume", estimated=True)
        if high == low:
            reference = low
        else:
            width = (high - low) / p["bins"]
            weights = [0.0] * p["bins"]
            for typical_price, item in zip(typical, window):
                index = min(p["bins"] - 1, int((typical_price - low) / width))
                weights[index] += item["volume"]
            chosen = max(range(p["bins"]), key=lambda index: (weights[index], -index))
            reference = low + (chosen + 0.5) * width
        return _decision(_cross(previous["close"], close, reference, reference, "up" if kind.endswith("up") else "down"), close, reference, day,
                         estimated=True, evidence={"method": "daily_typical_price_volume_bins", "bins": p["bins"]})
    if kind.startswith("sma_"):
        ma = lines["ma"]
        direction = "up" if kind.endswith("up") else "down"
        if kind.startswith("sma_slope"):
            before, value = ma[i - 1] - ma[i - 2], ma[i] - ma[i - 1]
            return _decision(_cross(before, value, 0, 0, direction), value, 0, day, evidence={"ma": ma[i], "previous_slope": before})
        return _decision(_cross(previous["close"], close, ma[i - 1], ma[i], direction), close, ma[i], day)
    if kind in {"ma_golden", "ma_dead"}:
        fast, slow = lines["fast"], lines["slow"]
        return _decision(_cross(fast[i - 1], fast[i], slow[i - 1], slow[i], "up" if kind == "ma_golden" else "down"), fast[i], slow[i], day)
    if kind.startswith("order_"):
        fast, middle, slow = (lines[key][i] for key in ("fast", "middle", "slow"))
        return _decision(fast > middle > slow if kind == "order_bullish" else fast < middle < slow, fast, slow, day, evidence={"middle": middle})
    if kind == "trend_reversal":
        ma, start = lines["ma"], i - p["confirmation"] + 1
        passed = ma[start - 1] <= ma[start - 2] and all(ma[j] > ma[j - 1] and rows[j]["close"] > ma[j] for j in range(start, i + 1))
        return _decision(passed, close, ma[i], day, evidence={"turn_date": rows[start]["date"], "confirmation": p["confirmation"]})
    if kind.startswith(("macd_", "sonar_")):
        values = lines["value"]
        before_ref, reference = (0, 0) if kind.endswith("zero") else (lines["signal"][i - 1], lines["signal"][i])
        return _decision(_cross(values[i - 1], values[i], before_ref, reference, p["direction"]), values[i], reference, day)
    if kind.startswith("stoch_"):
        k, d = lines["k"], lines["d"]
        if any(value is None for value in (k[i - 1], k[i], d[i - 1], d[i])):
            return _out("unavailable", day=day, reason="zero_price_range")
        passed = _le(k[i - 1], p["oversold"]) and _le(d[i - 1], p["oversold"]) and _cross(k[i - 1], k[i], d[i - 1], d[i])
        return _decision(passed, k[i], d[i], day, evidence={"previous_k": k[i - 1], "previous_d": d[i - 1], "oversold": p["oversold"]})
    if kind.startswith("rank_"):
        reference = None
        if kind == "rank_volume":
            value = row["volume"]
        elif kind == "rank_trading_value":
            value = row["trading_value"]
        elif kind == "rank_turnover":
            reference = row["shares"]
            value = 100 * (row["volume"] / reference)
        else:
            reference = rows[i - (20 if kind == "rank_return_20d" else 1)]["close"]
            value = 100 * (close / reference - 1)
        return _out("pass", value, reference, day, ranking=True, top_n=p["top_n"])
    if kind.startswith("intraday_"):
        count = p["period"] if kind == "intraday_volume" else 1
        window = rows[i - count:i + 1]
        stamps = [datetime.fromisoformat(item["timestamp"]) for item in window]
        if any(a.date() != b.date() or b - a != timedelta(minutes=10) for a, b in zip(stamps, stamps[1:])):
            return _out("unavailable", day=day, reason="missing_intraday_bars")
        if kind == "intraday_volume":
            reference = math.fsum(item["volume"] / count for item in window[:-1])
            if reference <= 0:
                return _out("unavailable", day=day, reason="zero_reference_volume")
            value = row["volume"] / reference
            return _decision(_ge(value, p["multiple"]), value, p["multiple"], day)
        value = 100 * (close / previous["close"] - 1)
        reference = p["threshold_pct"] if kind == "intraday_surge" else -p["threshold_pct"]
        return _decision(_ge(value, reference) if kind == "intraday_surge" else _le(value, reference), value, reference, day)
    raise AssertionError(f"unhandled strategy kind {kind}")


def evaluate_strategy(rows: list[dict], condition: dict) -> dict:
    """Evaluate latest bar, or most recent qualifying event in within_days.

    Daily rows must be in strict date order and already cut off at as_of. The
    caller verifies exchange-calendar coverage; this pure function verifies
    history length, date bounds, required values, and intraday cadence. EMA
    seeds use the same bounded span per event, independent of within_days or
    extra ancient history. Ranking returns the metric only; cross-sectional
    ranking belongs to the screener.
    """
    normalized = normalize_condition(condition)
    identifier, p, within = normalized["strategy_id"], normalized["params"], normalized["within_days"]
    entry, kind = _ENTRIES[identifier], _KINDS[identifier]
    if not isinstance(rows, list) or len(rows) > 10000:
        return _out("unavailable", reason="invalid_history")
    if not rows:
        return _out("unavailable", reason="insufficient_history")
    intraday = entry["timeframe"] == "10m"
    if intraday and any(not isinstance(item, dict) or "timestamp" not in item for item in rows):
        return _out("unavailable", reason="missing_intraday")
    required = [key for key in entry["required_data"] if key != "timestamp"]
    last_key = None
    dates = []
    for item in rows:
        if not isinstance(item, dict):
            return _out("unavailable", reason="invalid_history")
        try:
            key = datetime.fromisoformat(item["timestamp"]) if intraday else date.fromisoformat(item["date"])
            if intraday and ("T" not in item["timestamp"] and " " not in item["timestamp"]):
                return _out("unavailable", reason="missing_intraday")
            if not intraday and key.isoformat() != item["date"]:
                return _out("unavailable", reason="invalid_dates")
            if last_key is not None and key <= last_key:
                return _out("unavailable", reason="invalid_dates")
            last_key = key
            dates.append(key.date() if intraday else key)
        except (KeyError, ValueError, TypeError):
            return _out("unavailable", reason="invalid_dates")
    needed = _base_sessions(kind, p) + within - 1
    if len(rows) < needed:
        return _out("unavailable", reason="insufficient_history")
    if kind.endswith(("_52w", "_ytd")):
        earliest = dates[-within]
        floor = earliest - timedelta(days=365) if kind.endswith("_52w") else date(earliest.year, 1, 1)
        # Retain one observation on/before the calendar boundary as a coverage
        # witness, plus all observations that actually enter the indicator.
        witnesses = [i for i, observed in enumerate(dates) if observed <= floor]
        rows = rows[witnesses[-1]:] if witnesses else rows
    else:
        rows = rows[-needed:]
    for item in rows:
        for field in required:
            # shares / trading_value are same-date observations; historical
            # holes do not invalidate a current-day ranking metric.
            if field in {"shares", "trading_value"} and item is not rows[-1]:
                continue
            value = item.get(field)
            if not _finite_number(value):
                reason = f"missing_{field}" if value is None else f"invalid_{field}"
                return _out("unavailable", reason=reason)
            if value < 0 or (field not in {"volume", "trading_value"} and value == 0):
                return _out("unavailable", reason=f"invalid_{field}")
        if all(key in required for key in ("high", "low", "close")) and not item["low"] <= item["close"] <= item["high"]:
            return _out("unavailable", reason="invalid_ohlc")
    # Intraday callers may only have timestamp. Work on copies to preserve input.
    if intraday:
        rows = [{**item, "date": item["timestamp"][:10]} for item in rows]
    try:
        if kind.startswith(("macd_", "sonar_")):
            # Evaluate recursive indicators using a fixed local seed for each
            # candidate. Changing the search window cannot move a crossover.
            span = _base_sessions(kind, p)
            results = []
            for i in range(len(rows) - 1, len(rows) - within - 1, -1):
                window = rows[i - span + 1:i + 1]
                response = _at(window, span - 1, kind, p, _lines(window, kind, p))
                response["evidence"] = {"ema_seed": "sma", "seed_start": window[0]["date"], "seed_sessions": span}
                results.append(response)
        else:
            lines = _lines(rows, kind, p)
            results = [_at(rows, i, kind, p, lines) for i in range(len(rows) - 1, len(rows) - within - 1, -1)]
    except (ArithmeticError, ValueError):
        return _out("unavailable", reason="invalid_numeric_result")
    for result in results:
        if result["status"] == "pass":
            return result
    for result in results:
        if result["status"] == "unavailable":
            return result
    return results[0]
