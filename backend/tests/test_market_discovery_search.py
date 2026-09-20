"""Dynamic discovery: temporal truth, immutable parent scope and real sandbox replay."""
import hashlib
import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

import test_market_analysis_data as data_fixtures
import test_market_analysis_harness as harness_fixtures
from models.market_analysis import AnalysisSpec, ModelAction, RunRequest
from pipeline.market_analysis.analytics import screen, chart_data
from pipeline.market_analysis.expression import combine_status, evaluate_expression, normalize_expression
from pipeline.market_analysis.model import ClaudeModel, ModelError, ModelReply
from pipeline.market_analysis.store import Conflict, StoreError


def leaf(identifier, **params):
    return {"op": "condition", "condition": {"strategy_id": identifier, "params": params, "within_days": 1}}


def expression_spec(expression, **kwargs):
    return AnalysisSpec(mode="catalog", expression=expression, **kwargs).model_dump(mode="json")


def rows_for(values, volumes=None):
    dates = data_fixtures.trading_dates(len(values))
    return [{"code": "000001", "date": day, "open": value, "high": value + 1,
             "low": value - 1, "close": value, "volume": (volumes or [100] * len(values))[index]}
            for index, (day, value) in enumerate(zip(dates, values))], dates


class ExpressionSemanticsTests(unittest.TestCase):
    def evaluate(self, rows, days, expression):
        return evaluate_expression(rows, days, normalize_expression(expression))

    def test_prefix_optimization_matches_catalog_formulas(self):
        from pipeline.market_analysis.strategies import catalog, evaluate_strategy
        import math
        values = [100 + index / 4 + 8 * math.sin(index / 11) for index in range(600)]
        rows, days = rows_for(values, [100 + (index * 17) % 91 for index in range(600)])
        for entry in catalog():
            if entry["id"].startswith("rank_"):
                continue
            for within in ([1] if entry["timeframe"] != "1d" else [1, 20]):
                condition = {"strategy_id": entry["id"], "params": entry["defaults"], "within_days": within}
                with self.subTest(strategy=entry["id"], within=within):
                    expected = evaluate_strategy(rows, condition)
                    actual = self.evaluate(rows, days, {"op": "condition", "condition": condition})
                    for key in ("status", "date", "value", "reference", "reason"):
                        self.assertEqual(actual.get(key), expected.get(key))

    def test_three_valued_truth_table(self):
        for a in ("pass", "fail", "unavailable"):
            for b in ("pass", "fail", "unavailable"):
                expected_and = "fail" if "fail" in (a, b) else "unavailable" if "unavailable" in (a, b) else "pass"
                expected_or = "pass" if "pass" in (a, b) else "unavailable" if "unavailable" in (a, b) else "fail"
                self.assertEqual(combine_status("and", [a, b]), expected_and)
                self.assertEqual(combine_status("or", [a, b]), expected_or)
        self.assertEqual(combine_status("not", ["unavailable"]), "unavailable")

    def test_validation_rejects_ambiguous_and_unbounded_operations(self):
        invalid = [
            {"op": "xor", "children": [leaf("price_flat"), leaf("price_flat")]},
            {"op": "not", "child": leaf("price_flat"), "network": True},
            {"op": "and", "children": [leaf("price_flat")]},
            leaf("rank_volume"),
            {"op": "consecutive", "days": True, "child": leaf("price_flat")},
            {"op": "sequence", "within_days": 91, "children": [leaf("price_flat")] * 2},
            {"op": "sequence", "within_days": 90, "children": [leaf("price_flat")] * 5},
            {"op": "consecutive", "days": 2, "child": {"op": "not", "child": leaf("price_flat")}},
            {"op": "consecutive", "days": 2, "child": {"op": "condition", "condition": {"strategy_id": "price_flat", "within_days": 2}}},
            {"op": "and", "children": [{"op": "consecutive", "days": 60, "child": leaf("price_flat")}] * 9},
        ]
        deep = leaf("price_flat")
        for _ in range(7):
            deep = {"op": "not", "child": deep}
        invalid.append(deep)
        for expression in invalid:
            with self.subTest(expression=expression), self.assertRaises(ValidationError):
                expression_spec(expression)
        with self.assertRaises(ValidationError):
            AnalysisSpec(mode="catalog", expression=leaf("price_flat"), strategy_conditions=[{"strategy_id": "price_flat"}])

    def test_order_is_strict_and_gap_uses_observed_sessions(self):
        rows, days = rows_for([100] * 6 + [110, 110, 110], [100] * 8 + [200])
        sequence = {"op": "sequence", "within_days": 3, "max_gap_days": 2,
                    "children": [leaf("high_5d", price_field="close"), leaf("volume_increase")]}
        actual = self.evaluate(rows, days, sequence)
        self.assertEqual(actual["status"], "pass")
        self.assertEqual([event["date"] for event in actual["events"]], [days[-3], days[-1]])
        self.assertEqual([event["known_at"] for event in actual["events"]], [days[-3], days[-1]])
        self.assertEqual(self.evaluate(rows, days, {**sequence, "max_gap_days": 1})["status"], "fail")
        self.assertEqual(self.evaluate(rows, days, {**sequence, "children": list(reversed(sequence["children"]))})["status"], "fail")

    def test_same_day_is_explicit_and_future_events_are_excluded(self):
        rows, days = rows_for([100] * 6 + [110], [100] * 6 + [200])
        sequence = {"op": "sequence", "within_days": 2,
                    "children": [leaf("high_5d", price_field="close"), leaf("volume_increase")]}
        self.assertEqual(self.evaluate(rows, days, sequence)["status"], "fail")
        self.assertEqual(self.evaluate(rows, days, {**sequence, "allow_same_day": True})["status"], "pass")
        # Even if the caller has later rows, every evaluation reads a date prefix.
        result = self.evaluate(rows, days[:-1], {**sequence, "allow_same_day": True})
        self.assertNotEqual(result["status"], "pass")

    def test_consecutive_unknown_and_false_are_distinct(self):
        rows, days = rows_for([100] * 8)
        expr = {"op": "consecutive", "days": 3, "child": leaf("price_flat")}
        self.assertEqual(self.evaluate(rows, days, expr)["status"], "pass")
        self.assertEqual(self.evaluate(rows[:-3] + rows[-2:], days, expr)["status"], "unavailable")
        rows[-1].update(close=110, high=111)
        self.assertEqual(self.evaluate(rows[:-3] + rows[-2:], days, expr)["status"], "fail")

    def test_unknown_event_cannot_create_a_verified_sequence(self):
        rows, days = rows_for([100] * 8)
        sequence = {"op": "sequence", "within_days": 2,
                    "children": [leaf("price_surge_10m"), leaf("price_flat")]}
        self.assertEqual(self.evaluate(rows, days, sequence)["status"], "unavailable")
        self.assertEqual(self.evaluate(rows, days, {"op": "not", "child": sequence})["status"], "unavailable")


class ExpressionScreenTests(unittest.TestCase):
    setUp = data_fixtures.MarketDataTests.setUp
    tearDown = data_fixtures.MarketDataTests.tearDown
    connect = data_fixtures.MarketDataTests.connect
    insert = data_fixtures.MarketDataTests.insert
    snapshot = data_fixtures.MarketDataTests.snapshot

    def test_or_can_pass_with_visible_unknown_branch_but_not_unknown_alone(self):
        self.insert(data_fixtures.prices(count=25))
        folder = self.snapshot(verified=True)
        unknown = leaf("price_surge_10m")
        result = screen(folder, expression_spec({"op": "or", "children": [unknown, leaf("price_flat")]}))
        self.assertEqual(result["counts"]["matched"], 1)
        self.assertEqual(result["items"][0]["checks"]["expression.0"]["status"], "unavailable")
        self.assertEqual(result["items"][0]["checks"]["expression"]["status"], "pass")
        negative = screen(folder, expression_spec({"op": "not", "child": unknown}))
        self.assertEqual(negative["counts"]["matched"], 0)
        self.assertEqual(negative["counts"]["unevaluated"], 1)
        decisive = screen(folder, expression_spec({"op": "and", "children": [unknown, leaf("high_5d")]}))
        self.assertEqual((decisive["counts"]["failed"], decisive["counts"]["unevaluated"]), (1, 0))

    def test_failed_or_branches_are_not_drawn_as_chart_signals(self):
        self.insert(data_fixtures.prices(count=25))
        folder = self.snapshot(verified=True)
        spec = expression_spec({"op": "or", "children": [leaf("high_5d"), leaf("price_flat")]})
        result = screen(folder, spec)
        chart = chart_data(folder, "000001", spec, verified_result=result)
        self.assertNotIn("expression.0", [marker["kind"] for marker in chart["markers"]])
        self.assertIn("expression.1", [marker["kind"] for marker in chart["markers"]])

    def test_scope_missing_and_empty_never_expand_to_universe(self):
        self.insert(data_fixtures.prices(count=25))
        folder = self.snapshot(verified=True)
        for strategy in (expression_spec(leaf("price_flat")),
                         AnalysisSpec(mode="catalog", strategy_conditions=[{"strategy_id": "rank_volume"}]).model_dump(mode="json"),
                         AnalysisSpec(pattern="none", min_market_cap=0, require_52w=False, require_ma=False).model_dump(mode="json")):
            with self.subTest(mode=strategy["mode"], expression=strategy["expression"]):
                empty = screen(folder, {**strategy, "universe_codes": []})
                self.assertEqual(empty["counts"]["universe"], 0)
                missing = screen(folder, {**strategy, "universe_codes": ["999999"]})
                self.assertEqual(missing["counts"]["universe"], 1)
                self.assertEqual(missing["counts"]["unevaluated"], 1)
                self.assertEqual(missing["items"], [])

    def test_as_of_excludes_future_price_and_expression_evidence(self):
        rows = data_fixtures.prices(count=25)
        tail = list(rows[-1]); tail[2:6] = [120, 121, 119, 120]; rows[-1] = tuple(tail)
        self.insert(rows)
        folder = self.snapshot(verified=True)
        expression = leaf("high_5d", price_field="close")
        self.assertEqual(screen(folder, expression_spec(expression))["counts"]["matched"], 1)
        self.assertEqual(screen(folder, expression_spec(expression, as_of=rows[-2][1]))["counts"]["matched"], 0)


class FollowupModel(harness_fixtures.FixtureModel):
    received = None
    replacement = False

    def call(self, system, context, **kwargs):
        if context["spec"] is None and context.get("parent_search"):
            type(self).received = context["parent_search"]
            action = ({"action": "interpret", "spec": {"pattern": "none", "require_ma": False,
                       "require_52w": False, "min_market_cap": 0}} if self.replacement else
                      {"action": "interpret", "spec_patch": {"min_market_cap": 1}, "unsupported_conditions": ["미지원 산업 필터"]})
            return ModelReply(ModelAction.model_validate(action), .01)
        return super().call(system, context, **kwargs)


class FollowupHarnessTests(unittest.TestCase):
    setUp = harness_fixtures.HarnessTests.setUp
    tearDown = harness_fixtures.HarnessTests.tearDown

    def parent(self, cap=0):
        request = RunRequest(question="저장할 패턴", request_key=f"parent-{cap:015d}",
            spec=AnalysisSpec(pattern="none", require_52w=False, require_ma=True, ma_period=2, hold_days=1, min_market_cap=cap))
        run = self.service.create(request.model_dump(mode="json"))
        self.service.process(run["id"])
        state = self.service.store.read(run["id"])
        self.assertIsNotNone(state["result"], state["error"])
        return state

    def child(self, parent, **kwargs):
        return self.service.create(RunRequest(question="여기서 조건 변경", request_key="child-0000000001",
            parent_run_id=parent["id"], **kwargs).model_dump(mode="json"))

    def test_explicit_replay_uses_verified_snapshot_without_export_or_model(self):
        parent = self.parent()
        child = self.child(parent, spec_patch={})
        with patch.object(self.service, "exporter", side_effect=AssertionError("must reuse snapshot")):
            self.service.process(child["id"])
        result = self.service.store.read(child["id"])
        self.assertIsNone(result["error"])
        self.assertEqual(result["_snapshot_id"], parent["_snapshot_id"])
        self.assertEqual(result["_snapshot_hashes"], parent["_snapshot_hashes"])
        self.assertEqual(result["spec"]["as_of"], parent["result"]["as_of"])
        self.assertEqual(result["result"]["verification"]["status"], "matched")
        self.assertEqual(result["result"]["items"], parent["result"]["items"])
        self.assertEqual(harness_fixtures.FixtureModel.calls, 0)

    def test_candidate_scope_with_zero_matches_stays_empty_and_keeps_filters(self):
        parent = self.parent(cap=999_000_000_000)
        child = self.child(parent, scope="candidates", spec_patch={"min_market_cap": 0})
        self.service.process(child["id"])
        result = self.service.store.read(child["id"])
        self.assertIsNone(result["error"])
        self.assertEqual(result["spec"]["universe_codes"], [])
        self.assertTrue(result["spec"]["require_ma"])
        self.assertEqual(result["result"]["counts"]["universe"], 0)
        self.assertEqual(result["lineage"]["scope"], "candidates")
        self.assertIn("min_market_cap", [c["field"] for c in result["lineage"]["changes"]])

    def test_natural_patch_preserves_prior_conditions_and_marks_unsupported(self):
        parent = self.parent()
        self.service.model_factory = FollowupModel
        FollowupModel.replacement = False
        child = self.child(parent, scope="candidates")
        self.service.process(child["id"])
        result = self.service.store.read(child["id"])
        self.assertIsNone(result["error"])
        self.assertEqual(FollowupModel.received["spec"], parent["spec"])
        self.assertEqual(result["spec"]["min_market_cap"], 1)
        self.assertEqual(result["spec"]["universe_codes"], ["000001"])
        for field in ("mode", "pattern", "require_52w", "require_ma", "ma_period", "hold_days"):
            self.assertEqual(result["spec"][field], parent["spec"][field])
        self.assertEqual(result["result"]["unsupported_conditions"], ["미지원 산업 필터"])
        self.assertEqual(result["result"]["verification"]["status"], "matched")

    def test_full_model_replacement_is_rejected_before_calculation(self):
        parent = self.parent()
        self.service.model_factory = FollowupModel
        FollowupModel.replacement = True
        child = self.child(parent)
        self.service.process(child["id"])
        result = self.service.store.read(child["id"])
        self.assertIn("spec_patch", result["error"])
        self.assertEqual(result["steps"], 0)
        self.assertIsNone(result["result"])
        FollowupModel.replacement = False

    def test_latest_exports_new_snapshot_and_keeps_candidate_scope(self):
        parent = self.parent()
        child = self.child(parent, scope="candidates", date_policy="latest", spec_patch={})
        self.service.process(child["id"])
        result = self.service.store.read(child["id"])
        self.assertIsNone(result["error"])
        self.assertNotEqual(result["_snapshot_id"], parent["_snapshot_id"])
        self.assertEqual(result["spec"]["universe_codes"], ["000001"])
        self.assertIsNone(result["spec"]["as_of"])

    def test_unverified_parent_and_changed_input_block_followup(self):
        queued = self.service.create(RunRequest(question="아직 결과 없음", request_key="unverified-parent").model_dump(mode="json"))
        with self.assertRaises(Conflict):
            self.child(queued, spec_patch={})
        parent = self.parent()
        manifest = self.service.store.root / "snapshots" / parent["_snapshot_id"] / "manifest.json"
        manifest.chmod(0o644)
        manifest.write_text(manifest.read_text() + " ")
        with self.assertRaises(StoreError):
            self.child(parent, spec_patch={})

    def test_followup_cannot_override_fixed_date_scope_or_add_source_paths(self):
        parent = self.parent()
        for invalid in ({"as_of": "2025-01-02"}, {"universe_codes": None}, {"source_db": "/tmp/not-allowed"}):
            with self.subTest(patch=invalid), self.assertRaises(ValidationError):
                self.child(parent, spec_patch=invalid)
        with self.assertRaises(ValidationError):
            RunRequest(question="잘못된 후속", request_key="invalid-followup", scope="candidates")

    def test_cli_override_and_preflight_identify_missing_isolation_without_fallback(self):
        import os
        from types import SimpleNamespace
        with patch.dict(os.environ, {"MARKET_ANALYSIS_CLI": "/fixture/current/claude"}), \
             patch("pipeline.market_analysis.model.shutil.which", return_value="/fixture/old/claude"):
            model = ClaudeModel(self.root / "configured-model")
            self.assertEqual(model.executable, "/fixture/current/claude")
            preferred = ClaudeModel(self.root / "argument-model", executable="/fixture/explicit/claude")
            self.assertEqual(preferred.executable, "/fixture/explicit/claude")
        help_result = SimpleNamespace(returncode=0, stdout="--tools --strict-mcp-config --setting-sources "
            "--disable-slash-commands --no-session-persistence --max-budget-usd", stderr="secret-fixture")
        with patch("pipeline.market_analysis.model.subprocess.run", return_value=help_result) as call:
            with self.assertRaises(ModelError) as raised:
                model._preflight()
            self.assertIn("/fixture/current/claude", str(raised.exception))
            self.assertIn("--safe-mode", str(raised.exception))
            self.assertNotIn("secret-fixture", str(raised.exception))
            self.assertEqual(raised.exception.cost_usd, 0)
            self.assertEqual(call.call_count, 1)
            self.assertFalse(model._checked)
        help_result.stdout += " --safe-mode"
        with patch("pipeline.market_analysis.model.subprocess.run", return_value=help_result):
            model._preflight()
            self.assertTrue(model._checked)
        with patch("pipeline.market_analysis.model.subprocess.run", side_effect=FileNotFoundError("private-fixture")):
            with self.assertRaises(ModelError) as raised:
                preferred._preflight()
            self.assertIn("/fixture/explicit/claude", str(raised.exception))
            self.assertNotIn("private-fixture", str(raised.exception))

    def test_expression_real_sandbox_pins_extra_skills_and_matches_verifier(self):
        expression = {"op": "or", "children": [leaf("opening_gap_up"), leaf("price_surge_10m")]}
        run = self.service.create(RunRequest(question="상승갭 또는 10분봉 급등", request_key="expression-sandbox",
            spec=expression_spec(expression)).model_dump(mode="json"))
        self.service.process(run["id"])
        result = self.service.store.read(run["id"])
        self.assertIsNone(result["error"])
        self.assertEqual(result["result"]["verification"]["status"], "matched")
        self.assertEqual(set(result["result"]["verification"]["skill_hashes"]),
                         {"analytics.py", "strategies.py", "strategy_screen.py", "expression.py", "expression_screen.py"})
        self.assertEqual(harness_fixtures.FixtureModel.calls, 0)
        json.dumps(result, allow_nan=False)
