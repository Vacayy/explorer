"""Known-value tests for the deterministic strategy library (no network/DB)."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import math
import unittest

from backend.pipeline.market_analysis.strategies import (
    CATALOG_VERSION, catalog, evaluate_strategy, history_requirement,
    is_ranking, normalize_condition,
)


def bars(closes, start="2025-01-01", **fields):
    first = date.fromisoformat(start)
    return [{"date": (first + timedelta(days=i)).isoformat(),
             "open": float(close), "high": float(close) + 1,
             "low": float(close) - 1, "close": float(close),
             "volume": 100.0, "shares": 1000.0, **fields}
            for i, close in enumerate(closes)]


def condition(identifier, within_days=1, **params):
    return {"strategy_id": identifier, "params": params, "within_days": within_days}


def result(identifier, rows, within_days=1, **params):
    return evaluate_strategy(rows, condition(identifier, within_days, **params))


class CatalogTests(unittest.TestCase):
    def test_exact_60_distinct_catalog_entries_and_independent_copies(self):
        entries = catalog()
        self.assertEqual(len(entries), 60)
        self.assertEqual(len({item["id"] for item in entries}), 60)
        self.assertEqual([sum(item["category"] == category for item in entries)
                          for category in ("시세동향", "지표신호", "순위종목", "가격 구조")], [19, 25, 6, 10])
        self.assertTrue(CATALOG_VERSION)
        for item in entries:
            with self.subTest(strategy=item["id"]):
                self.assertEqual(set(item["defaults"]), set(item["parameters"]))
                self.assertTrue(item["formula"])
                normalized = normalize_condition({"strategy_id": item["id"]})
                self.assertEqual(normalized["params"], item["defaults"])
                self.assertEqual(normalized["within_days"], 1)
                self.assertEqual(is_ranking(normalized), item["category"] == "순위종목")
        entries[0]["defaults"]["tolerance_pct"] = 999
        self.assertEqual(catalog()[0]["defaults"]["tolerance_pct"], 0)
        self.assertEqual({item["id"] for item in entries if not item["available"]},
                         {"price_surge_10m", "price_drop_10m", "volume_spike_10m", "rank_trading_value"})

    def test_validation_rejects_unsupported_and_unbounded_work(self):
        bad = [None, [], {}, {"strategy_id": []}, {"strategy_id": "sql"},
               {"strategy_id": "high_20d", "sql": "select"},
               condition("high_20d", period=True), condition("high_20d", period=2.0),
               condition("high_20d", period=251), condition("high_20d", period=0),
               condition("high_20d", period=float("nan")),
               condition("price_flat", tolerance_pct=float("inf")),
               condition("high_20d", price_field="open"),
               condition("high_20d", extra=1), condition("high_20d", within_days=True),
               condition("high_20d", within_days=251), condition("high_20d", within_days=0),
               condition("rank_volume", within_days=2), condition("price_surge_10m", within_days=2),
               condition("golden_cross_20_60", fast=60, slow=20),
               condition("sma_bullish_order", middle=80), condition("rank_volume", top_n=0)]
        for value in bad:
            with self.subTest(condition=value), self.assertRaises(ValueError):
                normalize_condition(value)

    def test_history_requirements_include_previous_values_warmup_and_scan(self):
        expected = {"high_20d": 21, "sma_slope_up_20d": 22,
                    "sma_cross_up_20d": 21, "golden_cross_20_60": 61,
                    "sma_bullish_order": 60, "trend_reversal_confirmed": 24,
                    "macd_zero_cross": 250, "macd_signal_cross": 250,
                    "sonar_zero_cross": 250, "sonar_signal_cross": 250,
                    "stochastic_slow_buy": 19, "stochastic_fast_buy": 15,
                    "breakout_pullback_10d": 21, "rank_return_20d": 21}
        for identifier, sessions in expected.items():
            with self.subTest(strategy=identifier):
                self.assertEqual(history_requirement(condition(identifier), "2026-09-18")["sessions"], sessions)
                if not identifier.startswith("rank_"):
                    self.assertEqual(history_requirement(condition(identifier, within_days=4), "2026-09-18")["sessions"], sessions + 3)
        self.assertEqual(history_requirement(condition("high_52w"), "2026-09-18")["start_date"], "2025-09-18")
        self.assertEqual(history_requirement(condition("high_ytd"), "2026-09-18")["start_date"], "2026-01-01")
        self.assertLess(history_requirement(condition("high_52w", within_days=90), "2026-09-18")["start_date"], "2025-09-18")

    def test_every_strategy_dispatches_json_without_mutating_inputs(self):
        rows = bars([100 + math.sin(i / 8) * 10 + i / 100 for i in range(800)])
        rows[-1]["trading_value"] = 10000
        original = deepcopy(rows)
        for entry in catalog():
            with self.subTest(strategy=entry["id"]):
                response = evaluate_strategy(rows, condition(entry["id"]))
                self.assertIn(response["status"], {"pass", "fail", "unavailable"})
                if entry["timeframe"] == "10m":
                    self.assertEqual(response["reason"], "missing_intraday")
                else:
                    self.assertNotEqual(response["status"], "unavailable")
                json.dumps(response, allow_nan=False)
        self.assertEqual(rows, original)


class PriceStrategyTests(unittest.TestCase):
    def test_high_low_volume_strict_boundary_and_exclude_current(self):
        rows = bars([100] * 20 + [105])
        hit = result("high_20d", rows)
        self.assertEqual((hit["status"], hit["value"], hit["reference"]), ("pass", 106, 101))
        rows[-1].update(high=101, close=100, low=99)
        self.assertEqual(result("high_20d", rows)["status"], "fail")
        rows[-1]["high"] = 102
        self.assertEqual(result("high_20d", rows, price_field="close")["status"], "fail")
        rows[-1]["low"] = 98
        self.assertEqual(result("low_20d", rows)["status"], "pass")
        rows[-1]["low"] = 99
        self.assertEqual(result("low_20d", rows)["status"], "fail")
        rows[-1]["volume"] = 101
        self.assertEqual(result("volume_high_5d", rows)["status"], "pass")
        rows[-1]["volume"] = 100
        self.assertEqual(result("volume_high_5d", rows)["status"], "fail")
        self.assertEqual(result("high_20d", rows[1:])["reason"], "insufficient_history")

    def test_flat_and_gaps_use_explicit_references(self):
        rows = bars([100, 100])
        self.assertEqual(result("price_flat", rows)["status"], "pass")
        rows[-1]["close"] = 101
        self.assertEqual(result("price_flat", rows)["status"], "fail")
        self.assertEqual(result("price_flat", rows, tolerance_pct=2)["status"], "pass")
        rows[-1]["open"] = 103
        self.assertEqual(result("opening_gap_3pct", rows)["status"], "pass")
        self.assertEqual(result("opening_gap_up", rows)["status"], "pass")
        rows[-1]["open"] = 101
        self.assertEqual(result("opening_gap_up", rows)["status"], "fail")
        rows[-1]["open"] = 99
        self.assertEqual(result("opening_gap_down", rows)["status"], "fail")
        rows[-1]["open"] = 97
        self.assertEqual(result("opening_gap_down", rows)["status"], "pass")
        self.assertEqual(result("opening_gap_3pct", rows)["status"], "pass")

    def test_percentage_thresholds_handle_floating_point_boundary(self):
        rows = bars([100, 99])
        self.assertEqual(result("price_flat", rows, tolerance_pct=1)["status"], "pass")
        rows[-1]["open"] = 100.1
        self.assertEqual(result("opening_gap_3pct", rows, threshold_pct=0.1)["status"], "pass")
        rows[-1]["volume"] = 101
        self.assertEqual(result("volume_increase", rows, min_increase_pct=1)["status"], "fail")

    def test_calendar_extrema_use_complete_calendar_history_and_no_future(self):
        rows = bars([100] * 366 + [102], start="2025-01-01")
        rows[0]["high"] = 500  # outside the latest trailing 365-day window
        self.assertEqual(result("high_52w", rows)["status"], "pass")
        self.assertEqual(result("high_52w", rows[2:])["reason"], "insufficient_history")
        rows[-1]["high"] = 101
        self.assertEqual(result("high_52w", rows)["status"], "fail")
        rows[-1].update(low=97, close=98)
        self.assertEqual(result("low_52w", rows)["status"], "pass")
        ytd = bars([500, 100, 102], start="2025-12-31")
        self.assertEqual(result("high_ytd", ytd)["reference"], 101)
        self.assertEqual(result("high_ytd", ytd)["status"], "pass")
        self.assertEqual(result("high_ytd", ytd[:2])["reason"], "insufficient_history")

    def test_volume_change_zero_reference_and_near_high_boundaries(self):
        rows = bars([100] * 10 + [100], high=100, low=99)
        rows[-1]["volume"] = 200
        response = result("volume_increase", rows)
        self.assertEqual(response["value"], 100)
        self.assertEqual(response["status"], "pass")
        self.assertEqual(result("volume_increase", rows, min_increase_pct=100)["status"], "fail")
        rows[-2]["volume"] = 0
        self.assertEqual(result("volume_increase", rows)["reason"], "zero_reference_volume")
        for close, expected in ((99, "pass"), (100, "pass"), (98.99, "fail"), (100.01, "fail")):
            rows[-1]["close"] = close
            self.assertEqual(result("near_high_10d", rows)["status"], expected)

    def test_breakout_then_pullback_has_fixed_anchor_and_temporal_order(self):
        rows = bars([100] * 10 + [105, 102, 100, 99])
        response = result("breakout_pullback_10d", rows, breakout_lookback=3)
        self.assertEqual(response["status"], "pass")
        self.assertEqual(response["reference"], 99.99)
        self.assertEqual(response["evidence"]["breakout_date"], rows[10]["date"])
        self.assertEqual(response["evidence"]["breakout_level"], 101)
        self.assertEqual(result("breakout_pullback_10d", rows[:-1], breakout_lookback=2)["status"], "fail")
        rows[-1]["close"] = 99.99
        self.assertEqual(result("breakout_pullback_10d", rows, breakout_lookback=3)["status"], "fail")
        flat = bars([100] * 14)
        self.assertEqual(result("breakout_pullback_10d", flat, breakout_lookback=3)["reason"], "no_prior_breakout")

    def test_within_days_returns_latest_known_event_and_needs_full_window(self):
        rows = bars([100] * 20 + [105, 100, 106, 99])
        self.assertEqual(result("high_20d", rows)["status"], "fail")
        response = result("high_20d", rows, within_days=4)
        self.assertEqual(response["date"], rows[-2]["date"])
        self.assertEqual(response["status"], "pass")
        self.assertEqual(result("high_20d", rows, within_days=5)["reason"], "insufficient_history")
        before_future = result("high_20d", rows[:21])
        rows.append({**rows[-1], "date": "2025-02-01", "high": 10000})
        self.assertEqual(result("high_20d", rows[:21]), before_future)


class IndicatorStrategyTests(unittest.TestCase):
    def test_sma_slope_reversals_and_price_crosses(self):
        up = bars([100] * 21 + [110])
        down = bars([100] * 21 + [90])
        for period in (5, 20):
            self.assertEqual(result(f"sma_slope_up_{period}d", up)["status"], "pass")
            self.assertEqual(result(f"sma_slope_down_{period}d", down)["status"], "pass")
            self.assertEqual(result(f"sma_cross_up_{period}d", up)["status"], "pass")
            self.assertEqual(result(f"sma_cross_down_{period}d", down)["status"], "pass")
            self.assertEqual(result(f"sma_cross_up_{period}d", down)["status"], "fail")
            self.assertEqual(result(f"sma_slope_up_{period}d", bars([100] * 22))["status"], "fail")
        response = result("sma_slope_up_20d", up)
        self.assertAlmostEqual(response["value"], 0.5)
        self.assertAlmostEqual(response["evidence"]["ma"], 100.5)

    def test_golden_dead_cross_and_order_equality(self):
        for fast, slow in ((20, 60), (5, 20)):
            up = bars([100] * slow + [120])
            down = bars([100] * slow + [80])
            self.assertEqual(result(f"golden_cross_{fast}_{slow}", up)["status"], "pass")
            self.assertEqual(result(f"dead_cross_{fast}_{slow}", down)["status"], "pass")
            self.assertEqual(result(f"golden_cross_{fast}_{slow}", down)["status"], "fail")
        self.assertEqual(result("sma_bullish_order", bars(range(100, 160)))["status"], "pass")
        self.assertEqual(result("sma_bearish_order", bars(range(160, 100, -1)))["status"], "pass")
        self.assertEqual(result("sma_bullish_order", bars([100] * 60))["status"], "fail")
        self.assertEqual(result("sma_bearish_order", bars([100] * 60))["status"], "fail")

    def test_trend_confirmation_emits_only_at_confirmation_bar(self):
        rows = bars([100] * 21 + [102, 104, 106, 108])
        response = result("trend_reversal_confirmed", rows[:24])
        self.assertEqual(response["status"], "pass")
        self.assertEqual(response["evidence"]["turn_date"], rows[21]["date"])
        self.assertEqual(result("trend_reversal_confirmed", rows)["status"], "fail")
        self.assertEqual(result("trend_reversal_confirmed", rows[:23])["reason"], "insufficient_history")
        interrupted = bars([100] * 21 + [102, 99, 106])
        self.assertEqual(result("trend_reversal_confirmed", interrupted)["status"], "fail")

    def test_volume_profile_estimate_known_weighted_bin_and_tie(self):
        rows = bars([9, 9, 10, 10, 11], high=10, low=8)
        # Explicit representative prices 9,9,10,10; equal volume in two bins.
        for i in (2, 3):
            rows[i].update(high=11, low=9)
        rows[-2]["close"] = 10
        rows[-1].update(high=12, low=10)
        # Prior low=9/high=10; tie picks lower bin center=9.25. Previous
        # close10 already above that anchor, so there is no new crossing.
        response = result("volume_profile_up_20d", rows, period=4, bins=2)
        self.assertEqual(response["reference"], 9.25)
        self.assertTrue(response["estimated"])
        self.assertEqual(response["status"], "fail")
        flat = bars([100] * 20 + [102])
        response = result("volume_profile_up_20d", flat)
        self.assertEqual((response["reference"], response["status"]), (100, "pass"))
        flat[-1].update(close=98, high=99, low=97)
        self.assertEqual(result("volume_profile_down_20d", flat)["status"], "pass")
        for row in flat:
            row["volume"] = 0
        self.assertEqual(result("volume_profile_up_20d", flat)["reason"], "zero_reference_volume")

    def test_macd_sma_seed_and_signal_expected_values(self):
        rows = bars([100] * 249 + [110])
        # Initial EMAs and signal are exactly100/0. At the impulse:
        # MACD = 10*(2/13 - 2/27); EMA9(signal) = MACD*0.2.
        expected_macd = 10 * (2 / 13 - 2 / 27)
        for identifier in ("macd_zero_cross", "macd_signal_cross"):
            response = result(identifier, rows)
            self.assertEqual(response["status"], "pass")
            self.assertAlmostEqual(response["value"], expected_macd)
            self.assertAlmostEqual(response["reference"], expected_macd * 0.2 if "signal" in identifier else 0)
        down = bars([100] * 249 + [90])
        self.assertEqual(result("macd_signal_cross", down, direction="down")["status"], "pass")
        self.assertEqual(result("macd_signal_cross", down)["status"], "fail")
        self.assertEqual(result("macd_signal_cross", rows[-249:])["reason"], "insufficient_history")

    def test_sonar_uses_ema_difference_not_roc(self):
        rows = bars([100] * 249 + [110])
        expected_sonar = 20 / 21
        zero = result("sonar_zero_cross", rows)
        signal = result("sonar_signal_cross", rows)
        self.assertEqual(zero["status"], "pass")
        self.assertEqual(signal["status"], "pass")
        self.assertAlmostEqual(zero["value"], expected_sonar)
        self.assertAlmostEqual(signal["reference"], expected_sonar * 0.2)
        self.assertEqual(result("sonar_zero_cross", bars([100] * 250))["status"], "fail")

    def test_recursive_indicators_have_fixed_bounded_seed_and_window_invariance(self):
        for family, span in (("macd", 250), ("sonar", 250)):
            rows = bars([100] * 300 + [110])
            latest = result(f"{family}_zero_cross", rows)
            self.assertEqual(latest["status"], "pass")
            self.assertEqual(latest["value"], result(f"{family}_signal_cross", rows)["value"])
            self.assertEqual(latest, result(f"{family}_zero_cross", rows, within_days=10))
            rows[0]["close"] = float("nan")
            self.assertEqual(latest, result(f"{family}_zero_cross", rows))
            self.assertEqual(latest, result(f"{family}_zero_cross", rows[-span:]))
            # A malformed value inside the required seed still fails closed.
            rows[-span]["close"] = float("nan")
            self.assertEqual(result(f"{family}_zero_cross", rows)["status"], "unavailable")

    def test_stochastic_fast_and_slow_known_oversold_cross(self):
        rows = bars([102] * 20 + [110], high=200, low=100)
        fast = result("stochastic_fast_buy", rows)
        slow = result("stochastic_slow_buy", rows)
        self.assertEqual(fast["status"], "pass")
        self.assertEqual(slow["status"], "pass")
        self.assertAlmostEqual(fast["value"], 10)
        self.assertAlmostEqual(fast["reference"], 3.6)
        self.assertAlmostEqual(slow["value"], 3.6)
        self.assertAlmostEqual(slow["reference"], 2.32)
        above_oversold = bars([150] * 20 + [160], high=200, low=100)
        self.assertEqual(result("stochastic_fast_buy", above_oversold)["status"], "fail")
        self.assertEqual(result("stochastic_fast_buy", above_oversold, oversold=60)["status"], "pass")
        zero_range = bars([100] * 21, high=100, low=100)
        self.assertEqual(result("stochastic_slow_buy", zero_range)["reason"], "zero_price_range")


class DataAndRankingTests(unittest.TestCase):
    def test_ranking_metrics_are_actual_values_and_same_day_shares(self):
        rows = bars([100] * 20 + [120])
        rows[-1].update(volume=250, shares=1000, trading_value=29800)
        expected = {"rank_volume": 250, "rank_trading_value": 29800,
                    "rank_return_20d": 20, "rank_return_1d": 20,
                    "rank_volume_growth": 150, "rank_turnover": 25}
        for identifier, value in expected.items():
            with self.subTest(strategy=identifier):
                response = result(identifier, rows, top_n=5)
                self.assertEqual(response["status"], "pass")
                self.assertTrue(response["ranking"])
                self.assertEqual(response["top_n"], 5)
                self.assertAlmostEqual(response["value"], value)
        del rows[-1]["trading_value"]
        self.assertEqual(result("rank_trading_value", rows)["reason"], "missing_trading_value")
        rows[-1]["shares"] = None
        self.assertEqual(result("rank_turnover", rows)["reason"], "missing_shares")
        rows[-1]["shares"] = 0
        self.assertEqual(result("rank_turnover", rows)["reason"], "invalid_shares")
        rows[-1]["shares"] = 1000
        rows[0]["shares"] = None
        self.assertEqual(result("rank_turnover", rows)["status"], "pass")

    def test_bad_data_is_unavailable_not_false_or_nan_json(self):
        invalid_values = [float("nan"), float("inf"), -1, 0, True, "100", None]
        for value in invalid_values:
            with self.subTest(value=value):
                rows = bars([100] * 21)
                rows[-1]["high"] = value
                response = result("high_20d", rows)
                self.assertEqual(response["status"], "unavailable")
                json.dumps(response, allow_nan=False)
        rows = bars([100] * 21)
        rows[-1]["date"] = rows[-2]["date"]
        self.assertEqual(result("high_20d", rows)["reason"], "invalid_dates")
        rows[-1]["date"] = "2025-13-41"
        self.assertEqual(result("high_20d", rows)["reason"], "invalid_dates")
        self.assertEqual(result("high_20d", [None])["reason"], "invalid_history")
        rows = bars([100] * 21)
        rows[-1]["low"] = 110
        self.assertEqual(result("stochastic_fast_buy", rows)["reason"], "invalid_ohlc")
        self.assertEqual(result("high_20d", [rows[0]] * 10001)["reason"], "invalid_history")

    def test_intraday_requires_real_consecutive_same_session_timestamps(self):
        rows = bars([100] * 5 + [105])
        self.assertEqual(result("price_surge_10m", rows)["reason"], "missing_intraday")
        first = datetime.fromisoformat("2026-09-18T09:00:00+09:00")
        for i, row in enumerate(rows):
            row["timestamp"] = (first + timedelta(minutes=i * 10)).isoformat()
        rows[-1]["volume"] = 300
        self.assertEqual(result("price_surge_10m", rows)["status"], "pass")
        self.assertEqual(result("price_drop_10m", rows)["status"], "fail")
        self.assertEqual(result("volume_spike_10m", rows)["status"], "pass")
        self.assertEqual(result("volume_spike_10m", rows)["value"], 3)
        rows[-1]["close"] = 95
        self.assertEqual(result("price_drop_10m", rows)["status"], "pass")
        rows[-1]["timestamp"] = "2026-09-18T10:00:00+09:00"
        self.assertEqual(result("price_drop_10m", rows)["reason"], "missing_intraday_bars")
        rows[-1]["timestamp"] = "2026-09-19T09:00:00+09:00"
        self.assertEqual(result("price_drop_10m", rows)["reason"], "missing_intraday_bars")
        rows[-1]["timestamp"] = "2026-09-18"
        self.assertEqual(result("price_drop_10m", rows)["reason"], "missing_intraday")


if __name__ == "__main__":
    unittest.main()


PAD = [10, 10.1] * 6  # 피벗을 만들지 않는 앞부분(폭 2 기준) — lookback 최소 20을 채우기 위한 이력


def structure_bars(closes, lows=None, highs=None):
    rows = bars(PAD + list(closes))
    for offset, value in (lows or {}).items():
        rows[len(PAD) + offset]["low"] = float(value)
    for offset, value in (highs or {}).items():
        rows[len(PAD) + offset]["high"] = float(value)
    return rows


class PriceStructureTests(unittest.TestCase):
    """가격 구조(D-187): 피벗은 우측 폭이 지나야 확정되고, 선은 확정 피벗만으로 그린다."""

    ZIGZAG = [10, 9, 8, 7, 6, 7, 8, 9, 10, 11, 10, 9, 8, 9, 10, 11, 12, 13, 12, 11, 10, 11, 12, 13, 14, 15, 16, 17, 18]

    def test_higher_lows_uses_confirmed_troughs_only(self):
        rows = structure_bars(self.ZIGZAG)
        out = result("higher_lows", rows, pivot_width=2, swings=3, lookback=30)
        self.assertEqual(out["status"], "pass", out)
        self.assertEqual([p["price"] for p in out["evidence"]["pivots"]], [5.0, 7.0, 9.0])
        self.assertEqual((out["value"], out["reference"]), (9.0, 7.0))
        # 확정 고점은 12·14 두 개(마지막 상승 구간은 아직 미확정) → 고점 낮추기 실패, 스윙 부족 시 사유 표시
        lower = result("lower_highs", rows, pivot_width=2, swings=2, lookback=30)
        self.assertEqual((lower["status"], lower["value"], lower["reference"]), ("fail", 14.0, 12.0))
        self.assertEqual(result("lower_highs", rows, pivot_width=2, swings=4, lookback=30)["reason"], "insufficient_pivots")

    def test_resistance_break_crosses_last_confirmed_peak(self):
        series = [15, 17, 19, 20, 19, 17, 16, 15, 16, 17, 18, 19, 20, 21, 22]
        out = result("resistance_break", structure_bars(series), pivot_width=2, lookback=20, min_break_pct=0)
        self.assertEqual(out["status"], "pass", out)
        self.assertEqual((out["value"], out["reference"]), (22.0, 21.0))
        self.assertEqual(out["evidence"]["level"], 21.0)
        before = result("resistance_break", structure_bars(series[:-1]), pivot_width=2, lookback=20, min_break_pct=0)
        self.assertEqual(before["status"], "fail")
        margin = result("resistance_break", structure_bars(series), pivot_width=2, lookback=20, min_break_pct=5)
        self.assertEqual(margin["status"], "fail", "22 does not clear 21 × 1.05")

    def test_trendline_break_up_reports_the_crossing_day_within_window(self):
        series = [26, 28, 30, 28, 26, 24, 25, 26, 24, 22, 21, 22, 23, 24, 25]
        rows = structure_bars(series)
        out = result("trendline_break_up", rows, within_days=3, pivot_width=2, points=2, lookback=20)
        self.assertEqual(out["status"], "pass", out)
        self.assertEqual(out["date"], rows[len(PAD) + 13]["date"])
        self.assertAlmostEqual(out["evidence"]["slope"], -0.8)
        self.assertEqual([p["price"] for p in out["evidence"]["pivots"]], [31.0, 27.0])
        self.assertEqual(result("trendline_break_up", rows, within_days=1, pivot_width=2, points=2, lookback=20)["status"], "fail")

    def test_breakout_retest_rebreak_requires_touch_hold_and_new_high(self):
        series = [15, 17, 19, 20, 19, 17, 16, 15, 16, 17, 18, 19, 20, 21, 22, 23, 21.5, 21.2, 22, 23.5, 25.5]
        out = result("breakout_retest_rebreak", structure_bars(series, lows={17: 21.0}), pivot_width=2, lookback=20, tolerance_pct=2)
        self.assertEqual(out["status"], "pass", out)
        self.assertEqual(out["evidence"]["level"], 21.0)
        self.assertEqual(out["evidence"]["breakout_date"], structure_bars(series)[len(PAD) + 14]["date"])
        self.assertEqual((out["value"], out["reference"]), (25.5, 24.5))
        broken = result("breakout_retest_rebreak", structure_bars(series[:-2] + [19.5, 25.5]), pivot_width=2, lookback=20, tolerance_pct=2)
        self.assertEqual(broken["status"], "fail", "a close below level × 0.98 during the pullback is not a hold")

    def test_trendline_support_hold_and_swing_channel_share_the_trough_line(self):
        series = [10, 11, 12, 11, 10, 11, 12, 13, 12, 11, 12, 13, 14, 13, 12, 13, 14, 15, 14, 13.2, 14]
        hold = result("trendline_support_hold", structure_bars(series, lows={20: 12.1}), pivot_width=2, points=2, lookback=20, tolerance_pct=2)
        self.assertEqual(hold["status"], "pass", hold)
        self.assertAlmostEqual(hold["reference"], 12.2)
        far = result("trendline_support_hold", structure_bars(series), pivot_width=2, points=2, lookback=20, tolerance_pct=2)
        self.assertEqual(far["status"], "fail", "low 13.0 is 6% above the line")
        channel = result("channel_break_up", structure_bars(series[:-1] + [17]), pivot_width=2, points=2, lookback=20, method="swing", period=60, band_std=2)
        self.assertEqual(channel["status"], "pass", channel)
        self.assertAlmostEqual(channel["reference"], 16.6)
        self.assertEqual(len(channel["evidence"]["channel"]["upper"]), 2)

    def test_regression_channel_and_history_requirements(self):
        series = [100 + i * 0.5 + (0.3 if i % 2 else -0.3) for i in range(30)] + [120]
        out = result("channel_break_up", structure_bars(series), pivot_width=2, points=2, lookback=20, method="regression", period=20, band_std=2)
        self.assertEqual(out["status"], "pass", out)
        self.assertEqual(out["evidence"]["method"], "regression")
        self.assertEqual(history_requirement(condition("higher_lows", pivot_width=5, swings=3, lookback=120), "2026-09-18")["sessions"], 127)
        self.assertEqual(history_requirement(condition("channel_break_up", method="regression", period=200), "2026-09-18")["sessions"], 202)
        short = result("higher_lows", bars([10, 11, 12]), pivot_width=2, swings=2, lookback=20)
        self.assertEqual((short["status"], short["reason"]), ("unavailable", "insufficient_history"))
