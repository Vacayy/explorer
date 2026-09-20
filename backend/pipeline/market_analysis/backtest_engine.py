"""Causal, deterministic research backtests over already-loaded daily bars.

This module performs no file, database, network, broker, or clock operations.
Quantities are fixed at the decision close; only fills use the next open.
"""

from bisect import bisect_left, bisect_right
from collections import Counter, deque
from datetime import date, timedelta
import math

try:
    from .analytics import _patterns
except ImportError:  # The sandbox copies skill modules into one directory.
    from analytics import _patterns


ENGINE_VERSION = "explorer-backtest-v1"
STRATEGY_DEFINITIONS = (
    {"id": "buy_hold", "label": "고정 유니버스 단순 보유", "description": "첫 판단일 전체 적격 종목 동일 비중, 이후 유지"},
    {"id": "sma_cross", "label": "SMA5·20 상향 교차", "description": "최근 20거래일 상향 교차, 20거래일 수익률 순위"},
    {"id": "breakout_20d", "label": "20일 고가 돌파", "description": "최근 20거래일 종가가 직전 20봉 고가를 돌파"},
    {"id": "momentum_20d", "label": "20일 수익률 순위", "description": "20거래일 수익률 상위 종목"},
    {"id": "high52", "label": "52주 고가 돌파", "description": "최근 90거래일 종가가 직전 365일 고가를 돌파"},
    {"id": "high52_ihs", "label": "52주 돌파 + 역헤드앤숄더", "description": "같은 90거래일 내 확인 가능한 넥라인 돌파가 52주 돌파에 선행"},
    {"id": "high52_ihs_ma", "label": "복합 조건 + 20일선 유지", "description": "복합 조건과 최근 14거래일 종가 ≥ 각 날짜의 SMA20"},
)
STRATEGIES = STRATEGY_DEFINITIONS

_DEFAULTS = {
    "start_date": "2026-02-03", "split_date": "2026-07-01", "end_date": "2026-09-18",
    "initial_cash": 100_000_000.0, "max_positions": 20, "rebalance_every": 20,
    "buy_cost_bps": 25.0, "sell_cost_bps": 25.0, "min_market_cap": 0.0,
    "markets": ["KOSPI", "KOSDAQ"],
}
_PATTERN_SPEC = {"pivot_width": 3, "shoulder_tolerance": 0.15, "window_scope": "breakout"}
_WARNINGS = [
    "현재 수집 종목 중심의 유니버스이며 과거 상장·상폐 이력을 보증하지 않아 생존 편향이 남아 있습니다.",
    "공통 관측일은 공식 거래소 달력이 아니며 거래정지·가격 제한·체결 우선순위를 완전히 재현하지 않습니다.",
    "수정주가의 과거 기업행동 처리와 배당 포함 총수익률을 보증하지 않습니다.",
    "매수·매도 비용은 예시 시나리오입니다. 분수 수량과 현금 부족 시 비례 축소를 사용하는 연구 모형입니다.",
    "개발·평가 구간은 독립 자금으로 시작합니다. 최종 보유분은 강제 청산하지 않습니다.",
    "신호와 목표 수량은 판단일 종가에 고정하고 다음 관측일 시가로 체결합니다. 실패 주문은 이월하지 않습니다.",
]


def _number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    value = float(value)
    return value if value > 0 or (not positive and value == 0) else None


def _valid_bar(row):
    if not isinstance(row, dict):
        return False
    values = [_number(row.get(key), positive=True) for key in ("open", "high", "low", "close")]
    if any(value is None for value in values) or _number(row.get("volume")) is None:
        return False
    opening, high, low, close = values
    return low <= min(opening, close) <= max(opening, close) <= high


def _prefix_missing(values):
    prefix = [0]
    for value in values:
        prefix.append(prefix[-1] + int(value is None))
    return prefix


def _complete(prefix, left, right):
    return left >= 0 and right >= left and prefix[right + 1] == prefix[left]


class _Series:
    """Precompute causal daily features once, shared by all seven strategies."""

    def __init__(self, rows, calendar, year_starts):
        by_date = {row["date"]: row for row in rows if row["date"] <= calendar[-1]}
        self.rows = [by_date.get(day) for day in calendar]
        self.valid = [_valid_bar(row) for row in self.rows]
        self.closes = [float(row["close"]) if valid else None for row, valid in zip(self.rows, self.valid)]
        self.missing = _prefix_missing(self.closes)
        self.run_start = []
        beginning = 0
        sums = [0.0]
        for i, close in enumerate(self.closes):
            if close is None:
                beginning = i + 1
            self.run_start.append(beginning)
            sums.append(sums[-1] + (close or 0.0))
        self.sma5 = [(sums[i + 1] - sums[i - 4]) / 5 if _complete(self.missing, i - 4, i) else None for i in range(len(calendar))]
        self.sma20 = [(sums[i + 1] - sums[i - 19]) / 20 if _complete(self.missing, i - 19, i) else None for i in range(len(calendar))]
        self.momentum = [100.0 * (self.closes[i] / self.closes[i - 20] - 1) if _complete(self.missing, i - 20, i) else None for i in range(len(calendar))]
        self.cross_events = []
        self.breakout_events = []
        self.high52_events = []
        max20, max52 = deque(), deque()
        for i, row in enumerate(self.rows):
            if i and self.sma20[i - 1] is not None and self.sma20[i] is not None:
                if self.sma5[i - 1] <= self.sma20[i - 1] and self.sma5[i] > self.sma20[i]:
                    self.cross_events.append(i)
            while max20 and max20[0] < i - 20:
                max20.popleft()
            start = year_starts[i]
            while max52 and max52[0] < max(0, start):
                max52.popleft()
            if self.valid[i]:
                close = self.closes[i]
                if max20 and _complete(self.missing, i - 20, i) and close > float(self.rows[max20[0]]["high"]):
                    self.breakout_events.append(i)
                if max52 and _complete(self.missing, start, i) and close > float(self.rows[max52[0]]["high"]):
                    self.high52_events.append(i)
                for queue in (max20, max52):
                    while queue and float(self.rows[queue[-1]]["high"]) <= float(row["high"]):
                        queue.pop()
                    queue.append(i)
        self.pattern_cache = {}

    def has_event(self, events, left, right):
        return bisect_right(events, right) > bisect_left(events, left)

    def features(self, i, calendar, year_starts):
        """Each optional boolean is None when the required past is incomplete."""
        short_complete = _complete(self.missing, i - 39, i)
        long_complete = i >= 89 and _complete(self.missing, year_starts[i - 89], i)
        values = {
            "momentum_20d": self.momentum[i],
            "sma_cross": self.has_event(self.cross_events, i - 19, i) if short_complete else None,
            "breakout_20d": self.has_event(self.breakout_events, i - 19, i) if short_complete else None,
            "high52": self.has_event(self.high52_events, i - 89, i) if long_complete else None,
            "high52_ihs": None, "high52_ihs_ma": None,
        }
        if long_complete:
            ihs = False
            if values["high52"]:
                if i not in self.pattern_cache:
                    # The detector only sees confirmed bars available by this close.
                    prefix = self.rows[self.run_start[i]:i + 1]
                    self.pattern_cache[i] = _patterns(prefix, _PATTERN_SPEC, calendar[i - 89])
                high_dates = [calendar[index] for index in self.high52_events[bisect_left(self.high52_events, i - 89):bisect_right(self.high52_events, i)]]
                ihs = _ihs_before_high52(self.pattern_cache[i], high_dates, calendar[i], calendar[i - 89])
            values["high52_ihs"] = ihs
            values["high52_ihs_ma"] = ihs and all(self.closes[j] >= self.sma20[j] for j in range(i - 13, i + 1))
        return values


def _ihs_before_high52(patterns, high_dates, decision_date, window_start):
    """A retrospective trough must actually be known at the decision close."""
    return any(
        window_start <= pattern["breakout_date"] < high_date <= decision_date
        and pattern["known_at"] <= decision_date
        for pattern in patterns for high_date in high_dates
    )


def _normalize_spec(spec):
    result = {**_DEFAULTS, **spec}
    for key in ("start_date", "split_date", "end_date"):
        if date.fromisoformat(result[key]).isoformat() != result[key]:
            raise ValueError(f"Invalid {key}")
    if not result["start_date"] < result["split_date"] <= result["end_date"]:
        raise ValueError("Expected start_date < split_date <= end_date")
    for key in ("initial_cash", "buy_cost_bps", "sell_cost_bps", "min_market_cap"):
        if _number(result[key], positive=key == "initial_cash") is None:
            raise ValueError(f"Invalid {key}")
        result[key] = float(result[key])
    if max(result["buy_cost_bps"], result["sell_cost_bps"]) > 1000:
        raise ValueError("Trading cost must be at most 1000 bps")
    for key, maximum in (("max_positions", 500), ("rebalance_every", 250)):
        if isinstance(result[key], bool) or not isinstance(result[key], int) or not 1 <= result[key] <= maximum:
            raise ValueError(f"Invalid {key}")
    if not isinstance(result["markets"], list) or not result["markets"] or any(item not in ("KOSPI", "KOSDAQ", "KONEX", "UNKNOWN") for item in result["markets"]):
        raise ValueError("Invalid markets")
    result["markets"] = list(result["markets"])
    return result


def _market(value):
    value = str(value or "UNKNOWN").strip().upper()
    return "KOSDAQ" if value.startswith("KOSDAQ") else value


def _eligible_universe(universe, series, first, year_starts, spec):
    eligible, reasons = [], Counter()
    warmup = year_starts[first - 89] if first >= 89 else -1
    for stock in universe:
        code = stock["code"]
        if _market(stock.get("market")) not in spec["markets"]:
            reasons["market_not_selected"] += 1
        elif warmup < 0:
            reasons["insufficient_calendar_warmup"] += 1
        elif code not in series or series[code].rows[first] is None:
            reasons["missing_start_bar"] += 1
        elif not _complete(series[code].missing, warmup, first):
            reasons["incomplete_common_warmup"] += 1
        else:
            eligible.append(code)
    return sorted(eligible), dict(sorted(reasons.items())), warmup


def _signal_candidates(identifier, eligible, series, features, i, spec):
    candidates, unavailable = [], Counter()
    evaluated = 0
    for code in eligible:
        item = series[code]
        if not item.valid[i]:
            unavailable["missing_or_invalid_signal_bar"] += 1
            continue
        if spec["min_market_cap"]:
            cap = _number(item.rows[i].get("mktcap"), positive=True)
            if cap is None:
                unavailable["missing_signal_date_market_cap"] += 1
                continue
            if cap < spec["min_market_cap"]:
                evaluated += 1
                continue
        if identifier == "buy_hold":
            evaluated += 1
            candidates.append(code)
            continue
        feature = features[code]
        momentum = feature["momentum_20d"]
        match = momentum is not None if identifier == "momentum_20d" else feature[identifier]
        if match is None or momentum is None:
            unavailable["incomplete_signal_history"] += 1
            continue
        evaluated += 1
        if match:
            candidates.append(code)
    if identifier != "buy_hold":
        candidates.sort(key=lambda code: (-features[code]["momentum_20d"], code))
    return candidates, evaluated, unavailable


def _execute(pending, i, calendar, series, holdings, cash, last_prices, spec, trades, unfilled):
    """Net orders, causal target quantities, and proportional buy cash rationing."""
    target = {item["code"]: item["quantity"] for item in pending["targets"]}
    orders = []
    for code in sorted(set(holdings) | set(target)):
        desired = target.get(code, 0.0)
        quantity = desired - holdings.get(code, 0.0)
        if math.isclose(quantity, 0.0, abs_tol=1e-10):
            continue
        side = "buy" if quantity > 0 else "sell"
        row = series[code].rows[i]
        reason = None
        if row is None:
            reason = "missing_execution_bar"
        # High/low/close belong to the rest of the execution session and must
        # never gate an opening fill. Volume only models a no-trading session.
        elif _number(row.get("open"), positive=True) is None or _number(row.get("volume")) is None:
            reason = "invalid_execution_bar"
        elif row["volume"] <= 0:
            reason = "zero_execution_volume"
        if reason:
            unfilled.append({"date": calendar[i], "signal_date": pending["signal_date"], "code": code, "side": side, "quantity": abs(quantity), "target_quantity": desired, "reason": reason})
            continue
        orders.append({"code": code, "side": side, "quantity": abs(quantity), "target_quantity": desired, "price": float(row["open"])})
    buy_rate, sell_rate = spec["buy_cost_bps"] / 10_000, spec["sell_cost_bps"] / 10_000
    partial = 0

    def fill(order, ratio):
        nonlocal cash
        code, side = order["code"], order["side"]
        quantity = order["quantity"] * ratio
        notional = quantity * order["price"]
        cost = notional * (buy_rate if side == "buy" else sell_rate)
        if side == "sell":
            holdings[code] -= quantity
            cash += notional - cost
            if holdings[code] <= 1e-10:
                holdings.pop(code)
        else:
            newly_held = code not in holdings
            holdings[code] = holdings.get(code, 0.0) + quantity
            cash -= notional + cost
            if newly_held:
                last_prices[code] = (order["price"], calendar[i], "execution_open")
        if cash < 0 and abs(cash) < max(1e-7, spec["initial_cash"] * 1e-12):
            cash = 0.0
        if cash < 0:
            raise ArithmeticError("Cash became negative")
        trades.append({"date": calendar[i], "signal_date": pending["signal_date"], **order, "requested_quantity": order["quantity"], "quantity": quantity, "fill_ratio": ratio, "notional": notional, "cost": cost, "cash_after": cash})

    for order in orders:
        if order["side"] == "sell":
            fill(order, 1.0)
    buys = [order for order in orders if order["side"] == "buy"]
    needed = math.fsum(order["quantity"] * order["price"] * (1 + buy_rate) for order in buys)
    ratio = min(1.0, cash / needed) if needed else 1.0
    pending["buy_fill_ratio"] = ratio
    for order in buys:
        if ratio <= 0:
            unfilled.append({"date": calendar[i], "signal_date": pending["signal_date"], **order, "reason": "insufficient_cash"})
        else:
            fill(order, ratio)
            partial += int(ratio < 1 - 1e-12)
    return cash, partial


def _portfolio(definition, eligible, series, signal_cache, indices, calendar, spec):
    identifier = definition["id"]
    cash, peak = spec["initial_cash"], spec["initial_cash"]
    holdings, last_prices = {}, {}
    equity, trades, rebalances, unfilled = [], [], [], []
    pending = None
    partial_fills = stale_days = stale_position_days = 0
    for offset, i in enumerate(indices):
        if pending is not None:
            cash, partial = _execute(pending, i, calendar, series, holdings, cash, last_prices, spec, trades, unfilled)
            partial_fills += partial
            pending = None
        stale = []
        for code in holdings:
            row = series[code].rows[i]
            close = _number(row.get("close"), positive=True) if row else None
            if close is not None:
                last_prices[code] = (close, calendar[i], "close")
            else:
                stale.append(code)
        value = math.fsum(quantity * last_prices[code][0] for code, quantity in holdings.items())
        nav = cash + value
        peak = max(peak, nav)
        equity.append({"date": calendar[i], "nav": nav, "cash": cash, "exposure_pct": 100 * value / nav if nav else 0.0, "drawdown_pct": 100 * (nav / peak - 1), "positions": len(holdings), "stale_positions": len(stale)})
        stale_days += bool(stale)
        stale_position_days += len(stale)
        if offset % spec["rebalance_every"] or (identifier == "buy_hold" and offset):
            continue
        candidates, evaluated, unavailable = _signal_candidates(identifier, eligible, series, signal_cache[i], i, spec)
        selected = candidates if identifier == "buy_hold" else candidates[:spec["max_positions"]]
        slots = len(selected) if identifier == "buy_hold" else spec["max_positions"]
        targets = [{"code": code, "quantity": nav / slots / series[code].closes[i], "weight": 1.0 / slots, "signal_close": series[code].closes[i]} for code in selected]
        pending = {"signal_date": calendar[i], "execution_date": calendar[indices[offset + 1]] if offset + 1 < len(indices) else None, "candidates": len(candidates), "evaluated": evaluated, "unavailable": sum(unavailable.values()), "unavailable_by_reason": dict(sorted(unavailable.items())), "target_count": len(selected), "signal_nav": nav, "targets": targets}
        rebalances.append(pending)
        if pending["execution_date"] is None:
            target = {item["code"]: item["quantity"] for item in targets}
            for code in sorted(set(holdings) | set(target)):
                delta = target.get(code, 0.0) - holdings.get(code, 0.0)
                if abs(delta) > 1e-10:
                    unfilled.append({"date": calendar[i], "signal_date": calendar[i], "code": code, "side": "buy" if delta > 0 else "sell", "quantity": abs(delta), "target_quantity": target.get(code, 0.0), "reason": "no_next_session_in_segment"})
            pending = None
    final_holdings = [{"code": code, "quantity": quantity, "price": last_prices[code][0], "value": quantity * last_prices[code][0], "valuation_date": last_prices[code][1], "valuation_source": last_prices[code][2], "stale": last_prices[code][1] != calendar[indices[-1]] or last_prices[code][2] != "close"} for code, quantity in sorted(holdings.items())]
    return {
        **definition,
        "metrics": {"total_return_pct": 100 * (equity[-1]["nav"] / spec["initial_cash"] - 1), "max_drawdown_pct": min(row["drawdown_pct"] for row in equity), "exposure_avg_pct": math.fsum(row["exposure_pct"] for row in equity) / len(equity), "cost_total": math.fsum(trade["cost"] for trade in trades), "trades_count": len(trades), "ending_nav": equity[-1]["nav"], "unfilled_orders": len(unfilled), "partial_fills": partial_fills, "stale_valuation_days": stale_days, "stale_valuation_position_days": stale_position_days},
        "equity": equity, "rebalances": rebalances, "trades": trades, "holdings": final_holdings, "unfilled": unfilled,
    }


def compute_backtest(prices: dict[str, list[dict]], universe: list[dict], calendar: list[str], spec: dict) -> dict:
    """Run independent development/holdout portfolios over one immutable input."""
    normalized = _normalize_spec(spec)
    if not calendar or any(date.fromisoformat(day).isoformat() != day for day in calendar):
        raise ValueError("A valid observed calendar is required")
    if any(left >= right for left, right in zip(calendar, calendar[1:])):
        raise ValueError("Calendar must be strictly increasing")
    calendar = [day for day in calendar if day <= normalized["end_date"]]
    if not calendar:
        raise ValueError("No observed sessions before end_date")
    codes = [item["code"] for item in universe]
    if len(set(codes)) != len(codes):
        raise ValueError("Universe codes must be unique")
    year_starts = []
    for day in calendar:
        boundary = (date.fromisoformat(day) - timedelta(days=365)).isoformat()
        year_starts.append(bisect_left(calendar, boundary) if boundary >= calendar[0] else -1)
    # Only histories needed by the selected markets are materialized.
    series = {item["code"]: _Series(prices.get(item["code"], []), calendar, year_starts) for item in universe if _market(item.get("market")) in normalized["markets"]}
    segments, signal_cache = [], {}
    bounds = (("development", "개발 구간", normalized["start_date"], normalized["split_date"], False), ("holdout", "평가 구간", normalized["split_date"], normalized["end_date"], True))
    for identifier, label, start, end, inclusive in bounds:
        first = bisect_left(calendar, start)
        stop = bisect_right(calendar, end) if inclusive else bisect_left(calendar, end)
        indices = list(range(first, stop))
        if len(indices) < 2:
            raise ValueError(f"{identifier} requires at least two observed sessions")
        eligible, excluded, warmup = _eligible_universe(universe, series, first, year_starts, normalized)
        for i in indices[::normalized["rebalance_every"]]:
            cache = signal_cache.setdefault(i, {})
            for code in eligible:
                if code not in cache:
                    cache[code] = series[code].features(i, calendar, year_starts)
        results = [_portfolio(definition, eligible, series, signal_cache, indices, calendar, normalized) for definition in STRATEGY_DEFINITIONS]
        benchmark = results[0]["metrics"]["total_return_pct"]
        for result in results:
            result["metrics"]["return_vs_buy_hold_pp"] = result["metrics"]["total_return_pct"] - benchmark
        segments.append({"id": identifier, "label": label, "start_date": calendar[first], "end_date": calendar[stop - 1], "universe": {"requested": len(universe), "eligible": len(eligible), "excluded_by_reason": excluded, "warmup_start": calendar[warmup] if warmup >= 0 else None, "codes": eligible}, "strategies": results})
    return {"version": ENGINE_VERSION, "spec": normalized, "warnings": list(_WARNINGS), "segments": segments}
