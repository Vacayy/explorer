"""Catalog composition, data completeness and the real read-only execution path."""
import hashlib
import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import test_market_analysis_data as data_fixtures
import test_market_analysis_harness as harness_fixtures
from models.market_analysis import AnalysisSpec, RunRequest
from pipeline.market_analysis.analytics import chart_data, screen
from pipeline.market_analysis.strategies import catalog


def condition(strategy_id, **params):
    return {"strategy_id": strategy_id, "params": params, "within_days": 1}


def spec(*conditions, **kwargs):
    return AnalysisSpec(mode="catalog", strategy_conditions=list(conditions), **kwargs).model_dump(mode="json")


class CatalogScreenTests(unittest.TestCase):
    setUp = data_fixtures.MarketDataTests.setUp
    tearDown = data_fixtures.MarketDataTests.tearDown
    connect = data_fixtures.MarketDataTests.connect
    insert = data_fixtures.MarketDataTests.insert
    snapshot = data_fixtures.MarketDataTests.snapshot

    def test_rank_ties_filters_and_source_remains_unchanged(self):
        self.insert(data_fixtures.prices("000001", count=25, close=100), "000001")
        self.insert(data_fixtures.prices("000002", count=25, close=110), "000002")
        self.insert(data_fixtures.prices("000003", count=25, close=120, cap=1), "000003")
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        folder = self.snapshot(verified=True)
        result = screen(folder, spec(condition("rank_volume", top_n=1), min_market_cap=100))
        self.assertEqual([r["code"] for r in result["items"]], ["000001"])
        self.assertEqual(result["counts"], {"universe": 3, "matched": 1, "failed": 2,
                         "excluded": 0, "unevaluated": 0, "evaluated": 3})
        check = result["items"][0]["checks"]["rank_volume"]
        self.assertEqual((check["rank"], check["population"]), (1, 2))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)

    def test_independent_ranks_intersect_same_population(self):
        for code, volume, last_close in (("000001", 300, 101), ("000002", 200, 103), ("000003", 100, 102)):
            rows = data_fixtures.prices(code, count=25)
            row = list(rows[-1]); row[2:7] = [last_close, last_close + 1, last_close - 1, last_close, volume]
            rows[-1] = tuple(row)
            self.insert(rows, code)
        folder = self.snapshot(verified=True)
        conditions = [condition("rank_volume", top_n=2), condition("rank_return_1d", top_n=2)]
        first = screen(folder, spec(*conditions))
        second = screen(folder, spec(*reversed(conditions)))
        self.assertEqual([r["code"] for r in first["items"]], ["000002"])
        self.assertEqual(first["items"], second["items"])
        self.assertEqual(first["counts"]["failed"], 2)

    def test_missing_cap_does_not_exclude_unrequested_cap(self):
        rows = data_fixtures.prices(count=25, cap=None)
        self.insert(rows)
        folder = self.snapshot(verified=True)
        self.assertEqual(screen(folder, spec(condition("rank_volume")))["counts"]["matched"], 1)
        result = screen(folder, spec(condition("rank_volume"), min_market_cap=1))
        self.assertEqual(result["excluded"][0]["reason"], "missing_market_cap")

    def test_missing_data_is_unavailable_and_never_synthesized(self):
        rows = data_fixtures.prices(count=25)
        last = list(rows[-1]); last[-1] = None; rows[-1] = tuple(last)
        self.insert(rows)
        folder = self.snapshot(verified=True)
        for key, reason in (("rank_trading_value", "missing_trading_value"),
                            ("price_surge_10m", "missing_intraday"),
                            ("rank_turnover", "missing_shares")):
            with self.subTest(strategy=key):
                result = screen(folder, spec(condition(key)))
                self.assertEqual(result["counts"]["failed"], 0)
                self.assertEqual(result["counts"]["unevaluated"], 1)
                self.assertEqual(result["excluded"][0]["reason"], reason)
                self.assertEqual(result["status"], "partial")

    def test_calendar_hole_and_history_length_are_distinct(self):
        self.insert(data_fixtures.prices("000001", count=25), "000001")
        rows = data_fixtures.prices("000002", count=25)
        self.insert(rows[:-3] + rows[-2:], "000002")
        self.insert(data_fixtures.prices("000003", count=25)[-3:], "000003")
        result = screen(self.snapshot(verified=True), spec(condition("high_5d")))
        self.assertEqual({r["code"]: r["reason"] for r in result["excluded"]},
                         {"000002": "missing_observed_sessions", "000003": "insufficient_history"})

    def test_as_of_cutoff_and_chart_do_not_leak_future_or_unrequested_ma(self):
        rows = data_fixtures.prices(count=25)
        self.insert(rows)
        folder = self.snapshot(verified=True)
        fixed = spec(condition("rank_volume"), as_of=rows[-2][1])
        result = screen(folder, fixed)
        self.assertEqual(result["as_of"], rows[-2][1])
        chart = chart_data(folder, "000001", fixed)
        self.assertEqual(chart["prices"][-1]["time"], rows[-2][1])
        self.assertEqual(chart["ma"], [])

    def test_catalog_validation_and_discovery(self):
        app = FastAPI()
        from routers.analysis import router
        app.include_router(router)
        response = TestClient(app).get("/api/analysis/strategies")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 50)
        self.assertEqual(len({item["id"] for item in catalog()}), 50)
        for conditions in ([condition("invented")], [condition("rank_volume", top_n=float("nan"))],
                           [condition("rank_volume", injected=True)],
                           [condition("rank_volume"), condition("rank_volume")], [],
                           [{"strategy_id": "rank_volume", "within_days": 2}],
                           [{"strategy_id": "high_5d", "within_days": 251}]):
            with self.subTest(conditions=conditions), self.assertRaises(ValidationError):
                spec(*conditions)
        direct = RunRequest(question="저장 패턴 재실행", request_key="fixture-direct", spec={"mode": "pattern"})
        self.assertEqual(direct.spec.mode, "pattern")

    def test_catalog_can_refine_existing_legacy_conditions(self):
        self.insert(data_fixtures.prices("000001", count=25, cap=None), "000001")
        rows = data_fixtures.prices("000002", count=25)
        last = list(rows[-1]); last[2:6] = [80, 81, 79, 80]; rows[-1] = tuple(last)
        self.insert(rows, "000002")
        fixed = AnalysisSpec(mode="pattern", min_market_cap=0, pattern="none", require_52w=False,
                             require_ma=True, ma_period=20, hold_days=1,
                             strategy_conditions=[condition("rank_volume", top_n=1)]).model_dump(mode="json")
        result = screen(self.snapshot(verified=True), fixed)
        self.assertEqual([r["code"] for r in result["items"]], ["000001"])
        checks = result["items"][0]["checks"]
        self.assertEqual(checks["ma"]["status"], "pass")
        self.assertEqual(checks["market_cap"]["status"], "not_requested")
        self.assertEqual(checks["rank_volume"]["population"], 1)
        self.assertEqual(result["counts"]["failed"], 1)


class CatalogHarnessTests(unittest.TestCase):
    setUp = harness_fixtures.HarnessTests.setUp
    tearDown = harness_fixtures.HarnessTests.tearDown

    def test_explicit_selection_runs_sandbox_verifier_without_model(self):
        body = RunRequest(question="거래량 상위", request_key="catalog-fixture-01",
                          spec=spec(condition("rank_volume", top_n=1))).model_dump(mode="json")
        run = self.service.create(body)
        self.service.process(run["id"])
        state = self.service.store.read(run["id"])
        self.assertIsNone(state["error"])
        self.assertEqual(state["result"]["counts"]["matched"], 1)
        self.assertEqual(state["result"]["verification"]["status"], "matched")
        self.assertEqual(len(state["result"]["verification"]["skill_hashes"]), 3)
        self.assertEqual(state["steps"], 1)
        self.assertEqual(harness_fixtures.FixtureModel.calls, 0)
        self.assertEqual(state["cost_usd"], 0)
        with patch("pipeline.market_analysis.analytics.screen", side_effect=AssertionError("must use saved verification")):
            chart = self.service.chart(run["id"], "000001")
        self.assertEqual(chart["markers"][0]["label"], "거래량 상위")
        csv_artifact = next(a for a in state["artifacts"] if a["kind"] == "csv")
        _, content = self.service.store.artifact(run["id"], csv_artifact["id"])
        self.assertIn(b"rank_volume_rank", content)
        json.dumps(state["result"], allow_nan=False)

    def test_explicit_missing_intraday_is_partial_with_evidence(self):
        run = self.service.create(RunRequest(question="10분봉 급등", request_key="catalog-fixture-02",
            spec=spec(condition("price_surge_10m"))).model_dump(mode="json"))
        self.service.process(run["id"])
        state = self.service.store.read(run["id"])
        self.assertIsNone(state["error"])
        self.assertEqual(state["status"], "partial")
        self.assertEqual(state["result"]["counts"]["matched"], 0)
        self.assertEqual(state["result"]["excluded"][0]["reason"], "missing_intraday")
