"""Numerical execution, information timing, and missing-data regression tests."""

from copy import deepcopy
from datetime import date, timedelta
import json
import unittest

from backend.pipeline.market_analysis.backtest_engine import (
    ENGINE_VERSION, STRATEGIES, _ihs_before_high52, compute_backtest,
)


def fixture(codes=("A",), length=530):
    # Deliberately synthetic observed sessions, not an exchange calendar.
    calendar = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(length)]
    universe = [{"code": code, "name": code, "market": "KOSPI"} for code in codes]
    prices = {code: [{"code": code, "date": day, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0, "mktcap": 10_000_000_000.0} for day in calendar] for code in codes}
    return prices, universe, calendar


def specification(calendar, start=460, split=480, end=499, **changes):
    return {"start_date": calendar[start], "split_date": calendar[split], "end_date": calendar[end], "initial_cash": 1000.0, "max_positions": 1, "rebalance_every": 20, "buy_cost_bps": 0.0, "sell_cost_bps": 0.0, "min_market_cap": 0.0, "markets": ["KOSPI", "KOSDAQ"], **changes}


def set_bar(row, close, opening=None):
    opening = close if opening is None else opening
    row.update(open=float(opening), close=float(close), high=float(max(close, opening) + 1), low=float(min(close, opening) - 1))


def strategy(result, identifier="momentum_20d", segment=0):
    return next(item for item in result["segments"][segment]["strategies"] if item["id"] == identifier)


def pattern_fixture():
    prices, universe, calendar = fixture()
    anchors = [(0, 115), (420, 115.1), (435, 90), (443, 108), (447, 75), (451, 108), (455, 92), (456, 110), (457, 130), (500, 150), (529, 150)]
    for (left, start), (right, end) in zip(anchors, anchors[1:]):
        for i in range(left, right + 1):
            set_bar(prices["A"][i], start + (end - start) * (i - left) / (right - left))
    return prices, universe, calendar


class ExecutionTests(unittest.TestCase):
    def test_next_open_execution_and_causal_target_quantity_despite_gap(self):
        prices, universe, calendar = fixture()
        spec = specification(calendar)
        ordinary = strategy(compute_backtest(prices, universe, calendar, spec))
        set_bar(prices["A"][461], 100, opening=200)
        gapped = strategy(compute_backtest(prices, universe, calendar, spec))
        self.assertEqual(ordinary["rebalances"][0]["targets"], gapped["rebalances"][0]["targets"])
        self.assertEqual(gapped["rebalances"][0]["targets"][0]["quantity"], 10)
        self.assertEqual(gapped["trades"][0]["signal_date"], calendar[460])
        self.assertEqual(gapped["trades"][0]["date"], calendar[461])
        self.assertEqual(gapped["trades"][0]["price"], 200)
        self.assertEqual(gapped["trades"][0]["quantity"], 5)
        self.assertEqual(gapped["equity"][0]["positions"], 0)
        self.assertEqual(gapped["metrics"]["ending_nav"], 500)
        self.assertEqual(gapped["metrics"]["max_drawdown_pct"], -50)

    def test_sell_first_rotation_and_both_side_cost_accounting(self):
        prices, universe, calendar = fixture(("A", "B"))
        for i in range(450, len(calendar)):
            set_bar(prices["A"][i], 110)
            set_bar(prices["B"][i], 105 if i < 462 else 220)
        result = strategy(compute_backtest(prices, universe, calendar, specification(calendar, split=464, end=467, rebalance_every=2, buy_cost_bps=100, sell_cost_bps=200)))
        self.assertEqual([(item["code"], item["side"]) for item in result["trades"]], [("A", "buy"), ("A", "sell"), ("B", "buy")])
        self.assertEqual(result["trades"][1]["date"], result["trades"][2]["date"])
        initial_purchase = 1000 / 1.01
        sale_cash = initial_purchase * 0.98
        final_purchase = sale_cash / 1.01
        self.assertAlmostEqual(result["metrics"]["ending_nav"], final_purchase)
        self.assertAlmostEqual(result["metrics"]["cost_total"], 1000 - final_purchase)
        cash = 1000
        for trade in result["trades"]:
            cash += trade["notional"] - trade["cost"] if trade["side"] == "sell" else -trade["notional"] - trade["cost"]
            self.assertAlmostEqual(cash, trade["cash_after"])
            self.assertGreaterEqual(trade["cash_after"], 0)
        self.assertAlmostEqual(result["metrics"]["ending_nav"], cash + sum(item["value"] for item in result["holdings"]))

    def test_open_fill_does_not_depend_on_execution_session_high_low_close(self):
        prices, universe, calendar = fixture()
        spec = specification(calendar, split=462, end=465)
        ordinary = strategy(compute_backtest(prices, universe, calendar, spec), "buy_hold")
        prices["A"][461].update(high=None, low=None, close=None)
        missing_close = strategy(compute_backtest(prices, universe, calendar, spec), "buy_hold")
        self.assertEqual(ordinary["trades"], missing_close["trades"])
        self.assertEqual(missing_close["metrics"]["ending_nav"], 1000)
        self.assertEqual(missing_close["metrics"]["stale_valuation_days"], 1)
        self.assertEqual(missing_close["holdings"][0]["valuation_source"], "execution_open")
        self.assertTrue(missing_close["holdings"][0]["stale"])

    def test_reentry_with_missing_close_resets_old_mark_to_current_execution_open(self):
        prices, universe, calendar = fixture(("A", "B"))
        for i in range(450, len(calendar)):
            set_bar(prices["A"][i], 110 if i < 464 else 440)
            set_bar(prices["B"][i], 100 if i < 462 else 220)
        set_bar(prices["A"][465], 440, opening=300)
        prices["A"][465]["close"] = None
        portfolio = strategy(compute_backtest(prices, universe, calendar, specification(calendar, split=466, end=469, rebalance_every=2)))
        self.assertEqual([(trade["code"], trade["side"]) for trade in portfolio["trades"]], [("A", "buy"), ("A", "sell"), ("B", "buy"), ("B", "sell"), ("A", "buy")])
        holding = portfolio["holdings"][0]
        self.assertEqual(holding["code"], "A")
        self.assertEqual(holding["price"], 300)  # The old A position was marked at 110.
        self.assertEqual(holding["valuation_date"], calendar[465])
        self.assertEqual(holding["valuation_source"], "execution_open")
        self.assertTrue(holding["stale"])
        self.assertAlmostEqual(portfolio["metrics"]["ending_nav"], 1000)
        self.assertEqual(portfolio["metrics"]["stale_valuation_days"], 1)

    def test_unchanged_target_does_not_sell_and_rebuy(self):
        prices, universe, calendar = fixture()
        result = compute_backtest(prices, universe, calendar, specification(calendar, split=465, end=469, rebalance_every=1))
        portfolio = strategy(result)
        self.assertEqual(len(portfolio["rebalances"]), 5)
        self.assertEqual(len(portfolio["trades"]), 1)
        self.assertEqual(portfolio["metrics"]["ending_nav"], 1000)
        self.assertEqual(len(strategy(result, "buy_hold")["rebalances"]), 1)

    def test_cash_scaling_is_proportional_and_independent_of_universe_order(self):
        prices, universe, calendar = fixture(("A", "B"))
        set_bar(prices["A"][461], 100, opening=200)
        spec = specification(calendar, max_positions=2, buy_cost_bps=25)
        first = compute_backtest(prices, universe, calendar, spec)
        reverse = compute_backtest(prices, list(reversed(universe)), calendar, spec)
        trades = strategy(first)["trades"]
        self.assertEqual(strategy(first), strategy(reverse))
        self.assertEqual([trade["requested_quantity"] for trade in trades], [5, 5])
        self.assertAlmostEqual(trades[0]["fill_ratio"], 1000 / (1500 * 1.0025))
        self.assertEqual(trades[0]["fill_ratio"], trades[1]["fill_ratio"])
        self.assertAlmostEqual(trades[0]["quantity"], trades[1]["quantity"])
        self.assertEqual(strategy(first)["metrics"]["partial_fills"], 2)
        self.assertEqual(strategy(first)["metrics"]["unfilled_orders"], 0)

    def test_unused_slots_stay_in_cash_and_buy_hold_uses_all_eligible(self):
        prices, universe, calendar = fixture(("A", "B"))
        result = compute_backtest(prices, universe, calendar, specification(calendar, max_positions=4))
        limited = strategy(result)
        self.assertEqual(limited["equity"][-1]["cash"], 500)
        self.assertEqual(limited["equity"][-1]["exposure_pct"], 50)
        self.assertEqual(strategy(result, "buy_hold")["equity"][-1]["cash"], 0)
        self.assertEqual(strategy(result, "buy_hold")["equity"][-1]["positions"], 2)

    def test_final_session_orders_do_not_cross_segment_or_liquidate_holdings(self):
        prices, universe, calendar = fixture(("A", "B"))
        for i in range(450, len(calendar)):
            set_bar(prices["A"][i], 110)
            set_bar(prices["B"][i], 100 if i < 461 else 300)
        result = strategy(compute_backtest(prices, universe, calendar, specification(calendar, split=462, end=465, rebalance_every=1)))
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["holdings"][0]["code"], "A")
        self.assertIsNone(result["rebalances"][-1]["execution_date"])
        self.assertEqual(len(result["unfilled"]), 2)
        self.assertEqual({item["reason"] for item in result["unfilled"]}, {"no_next_session_in_segment"})


class CoverageAndTimingTests(unittest.TestCase):
    def test_zero_volume_blocks_fill_but_not_mark_and_does_not_retry(self):
        prices, universe, calendar = fixture()
        prices["A"][461]["volume"] = 0
        result = compute_backtest(prices, universe, calendar, specification(calendar))
        portfolio = strategy(result, "buy_hold")
        self.assertEqual(result["segments"][0]["universe"]["eligible"], 1)
        self.assertEqual(portfolio["trades"], [])
        self.assertEqual(portfolio["metrics"]["ending_nav"], 1000)
        self.assertEqual(portfolio["unfilled"][0]["reason"], "zero_execution_volume")
        self.assertEqual(len(portfolio["unfilled"]), 1)
        # A held zero-volume bar still has an observable closing mark.
        prices["A"][461]["volume"] = 1000
        prices["A"][462]["volume"] = 0
        set_bar(prices["A"][462], 120)
        portfolio = strategy(compute_backtest(prices, universe, calendar, specification(calendar)), "buy_hold")
        self.assertEqual(portfolio["equity"][2]["nav"], 1200)
        self.assertEqual(portfolio["equity"][2]["stale_positions"], 0)

    def test_missing_future_execution_does_not_ex_post_remove_stock(self):
        prices, universe, calendar = fixture()
        del prices["A"][461]
        result = compute_backtest(prices, universe, calendar, specification(calendar))
        self.assertEqual(result["segments"][0]["universe"]["eligible"], 1)
        portfolio = strategy(result, "buy_hold")
        self.assertEqual(portfolio["metrics"]["trades_count"], 0)
        self.assertEqual(portfolio["unfilled"][0]["reason"], "missing_execution_bar")
        self.assertEqual(len(portfolio["unfilled"]), 1)

    def test_gap_keeps_held_shares_and_stale_marks_then_recovers(self):
        prices, universe, calendar = fixture()
        set_bar(prices["A"][464], 120)
        prices["A"] = [row for row in prices["A"] if row["date"] not in {calendar[462], calendar[463]}]
        result = compute_backtest(prices, universe, calendar, specification(calendar, split=465, end=469))
        portfolio = strategy(result, "buy_hold")
        self.assertEqual(result["segments"][0]["universe"]["eligible"], 1)
        self.assertEqual(portfolio["metrics"]["stale_valuation_days"], 2)
        self.assertEqual(portfolio["equity"][2]["nav"], 1000)
        self.assertEqual(portfolio["equity"][3]["positions"], 1)
        self.assertEqual(portfolio["equity"][-1]["nav"], 1200)
        self.assertFalse(portfolio["holdings"][0]["stale"])
        self.assertEqual(portfolio["holdings"][0]["quantity"], 10)

    def test_bad_execution_bar_is_explicit_and_final_missing_close_is_stale(self):
        prices, universe, calendar = fixture()
        prices["A"][461]["open"] = 0
        result = strategy(compute_backtest(prices, universe, calendar, specification(calendar)), "buy_hold")
        self.assertEqual(result["unfilled"][0]["reason"], "invalid_execution_bar")
        prices["A"][461]["open"] = 100
        prices["A"][479]["close"] = None
        result = strategy(compute_backtest(prices, universe, calendar, specification(calendar)), "buy_hold")
        self.assertEqual(result["holdings"][0]["valuation_date"], calendar[478])
        self.assertTrue(result["holdings"][0]["stale"])
        self.assertEqual(result["metrics"]["ending_nav"], 1000)

    def test_each_segment_starts_with_independent_cash_and_no_holdings(self):
        prices, universe, calendar = fixture()
        for i in range(465, len(calendar)):
            set_bar(prices["A"][i], 200)
        result = compute_backtest(prices, universe, calendar, specification(calendar))
        self.assertEqual(strategy(result, "buy_hold")["metrics"]["ending_nav"], 2000)
        holdout = strategy(result, "buy_hold", 1)
        self.assertEqual(holdout["equity"][0]["nav"], 1000)
        self.assertEqual(holdout["equity"][0]["positions"], 0)
        self.assertEqual(holdout["trades"][0]["signal_date"], calendar[480])
        self.assertEqual(holdout["trades"][0]["quantity"], 5)

    def test_future_changes_do_not_change_earlier_segment_or_past_targets(self):
        prices, universe, calendar = pattern_fixture()
        spec = specification(calendar)
        before = compute_backtest(prices, universe, calendar, spec)
        changed = deepcopy(prices)
        for row in changed["A"][480:]:
            set_bar(row, 10_000)
            row["mktcap"] = 999_999_999_999
        after = compute_backtest(changed, universe, calendar, spec)
        self.assertEqual(before["segments"][0], after["segments"][0])
        # Extra bars strictly beyond the requested end cannot alter any output.
        changed = deepcopy(prices)
        for row in changed["A"][500:]:
            set_bar(row, 0.1)
        self.assertEqual(before, compute_backtest(changed, universe, calendar, spec))
        self.assertEqual(before, compute_backtest(prices, universe, calendar[:500], spec))

    def test_common_warmup_and_market_filter_are_fixed_at_segment_start(self):
        prices, universe, calendar = fixture(("GOOD", "GAP", "IPO", "OTHER"))
        universe[0]["market"] = "KOSDAQ GLOBAL"
        universe[3]["market"] = "KONEX"
        prices["GAP"] = [row for row in prices["GAP"] if row["date"] != calendar[100]]
        prices["IPO"] = prices["IPO"][430:]
        result = compute_backtest(prices, universe, calendar, specification(calendar))
        coverage = result["segments"][0]["universe"]
        self.assertEqual(coverage["codes"], ["GOOD"])
        self.assertEqual(coverage["requested"], coverage["eligible"] + sum(coverage["excluded_by_reason"].values()))
        self.assertEqual(coverage["excluded_by_reason"], {"incomplete_common_warmup": 2, "market_not_selected": 1})
        earlier = compute_backtest(prices, universe, calendar, specification(calendar, start=450))
        self.assertEqual(earlier["segments"][0]["universe"]["eligible"], 0)
        self.assertEqual(earlier["segments"][0]["universe"]["excluded_by_reason"]["insufficient_calendar_warmup"], 3)

    def test_market_cap_uses_decision_date_without_latest_value_fill(self):
        prices, universe, calendar = fixture()
        prices["A"][460]["mktcap"] = None
        prices["A"][461]["mktcap"] = 1
        result = strategy(compute_backtest(prices, universe, calendar, specification(calendar, split=464, end=467, rebalance_every=1, min_market_cap=1_000_000_000)))
        self.assertEqual(result["rebalances"][0]["unavailable_by_reason"], {"missing_signal_date_market_cap": 1})
        self.assertEqual(result["rebalances"][1]["candidates"], 0)
        self.assertEqual(result["rebalances"][1]["evaluated"], 1)
        self.assertEqual(result["rebalances"][2]["target_count"], 1)
        self.assertEqual(result["trades"][0]["date"], calendar[463])

    def test_empty_universe_is_reported_without_nan_or_fake_trades(self):
        prices, universe, calendar = fixture()
        universe[0]["market"] = "UNKNOWN"
        result = compute_backtest(prices, universe, calendar, specification(calendar))
        self.assertEqual(result["version"], ENGINE_VERSION)
        self.assertEqual(len(STRATEGIES), 7)
        for segment in result["segments"]:
            self.assertEqual(len(segment["strategies"]), 7)
            for portfolio in segment["strategies"]:
                self.assertEqual(portfolio["metrics"]["total_return_pct"], 0)
                self.assertEqual(portfolio["metrics"]["ending_nav"], 1000)
                self.assertEqual(portfolio["trades"], [])
        json.dumps(result, allow_nan=False)


class SignalTests(unittest.TestCase):
    def test_sma_cross_and_20_bar_breakout_event_window_boundaries(self):
        prices, universe, calendar = fixture()
        for row in prices["A"][460:]:
            set_bar(row, 120)
        result = compute_backtest(prices, universe, calendar, specification(calendar, start=479, split=481, end=485, rebalance_every=1))
        for identifier in ("sma_cross", "breakout_20d"):
            portfolio = strategy(result, identifier)
            self.assertEqual(portfolio["rebalances"][0]["target_count"], 1)  # Event at inclusive oldest session.
            self.assertEqual(portfolio["rebalances"][1]["target_count"], 0)  # One session later it has expired.

    def test_20_day_breakout_uses_prior_high_rather_than_prior_close(self):
        prices, universe, calendar = fixture()
        prices["A"][459]["high"] = 200
        for row in prices["A"][460:]:
            set_bar(row, 120)
        result = compute_backtest(prices, universe, calendar, specification(calendar))
        self.assertEqual(strategy(result, "breakout_20d")["rebalances"][0]["target_count"], 0)
        self.assertEqual(strategy(result, "sma_cross")["rebalances"][0]["target_count"], 1)

    def test_actual_pattern_is_unavailable_before_right_pivot_confirmation(self):
        prices, universe, calendar = pattern_fixture()
        result = compute_backtest(prices, universe, calendar, specification(calendar, start=457, split=463, end=469, rebalance_every=1))
        ordinary = strategy(result, "high52")
        compound = strategy(result, "high52_ihs")
        self.assertEqual(ordinary["rebalances"][0]["target_count"], 1)
        self.assertEqual(compound["rebalances"][0]["target_count"], 0)
        self.assertEqual(compound["rebalances"][1]["signal_date"], calendar[458])
        self.assertEqual(compound["rebalances"][1]["target_count"], 1)
        self.assertEqual(compound["trades"][0]["date"], calendar[459])

    def test_pattern_confirmation_and_strict_event_order_boundaries(self):
        patterns = [{"breakout_date": "2026-06-02", "known_at": "2026-06-05"}]
        self.assertFalse(_ihs_before_high52(patterns, ["2026-06-03"], "2026-06-04", "2026-06-01"))
        self.assertTrue(_ihs_before_high52(patterns, ["2026-06-03"], "2026-06-05", "2026-06-01"))
        self.assertFalse(_ihs_before_high52(patterns, ["2026-06-02"], "2026-06-05", "2026-06-01"))
        self.assertFalse(_ihs_before_high52(patterns, ["2026-06-06"], "2026-06-05", "2026-06-01"))
        self.assertFalse(_ihs_before_high52(patterns, ["2026-06-06"], "2026-06-07", "2026-06-03"))

    def test_ma_ablation_checks_all_fourteen_dates_not_only_latest(self):
        prices, universe, calendar = pattern_fixture()
        spec = specification(calendar, start=482, split=490, end=499)
        baseline = compute_backtest(prices, universe, calendar, spec)
        self.assertEqual(strategy(baseline, "high52_ihs_ma")["rebalances"][0]["target_count"], 1)
        set_bar(prices["A"][477], 95)
        changed = compute_backtest(prices, universe, calendar, spec)
        self.assertEqual(strategy(changed, "high52_ihs")["rebalances"][0]["target_count"], 1)
        self.assertEqual(strategy(changed, "high52_ihs_ma")["rebalances"][0]["target_count"], 0)

    def test_52_week_reference_is_365_calendar_days_and_excludes_current_bar(self):
        prices, universe, calendar = fixture()
        prices["A"][94]["high"] = 200  # 366 calendar days before decision.
        set_bar(prices["A"][460], 120)
        spec = specification(calendar)
        result = compute_backtest(prices, universe, calendar, spec)
        self.assertEqual(strategy(result, "high52")["rebalances"][0]["target_count"], 1)
        prices["A"][95]["high"] = 200  # Exactly 365 days belongs to reference.
        result = compute_backtest(prices, universe, calendar, spec)
        self.assertEqual(strategy(result, "high52")["rebalances"][0]["target_count"], 0)

    def test_rank_ties_use_code_and_do_not_backfill_missing_signal_history(self):
        prices, universe, calendar = fixture(("B", "A"))
        result = compute_backtest(prices, universe, calendar, specification(calendar))
        self.assertEqual(strategy(result)["rebalances"][0]["targets"][0]["code"], "A")
        # A gap after segment start keeps membership but makes subsequent ranking unavailable.
        prices["A"] = [row for row in prices["A"] if row["date"] != calendar[461]]
        result = strategy(compute_backtest(prices, universe, calendar, specification(calendar, split=465, end=469, rebalance_every=2)))
        self.assertEqual(result["rebalances"][1]["targets"][0]["code"], "B")
        self.assertEqual(result["rebalances"][1]["unavailable"], 1)


if __name__ == "__main__":
    unittest.main()
