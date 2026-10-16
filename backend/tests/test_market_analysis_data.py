"""Read-only export and deterministic screening tests on disposable fixtures."""

import hashlib
from contextlib import contextmanager
import json
from pathlib import Path
import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import pyarrow.parquet as pq

from pipeline.market_analysis.analytics import chart_data, screen
from pipeline.market_analysis.snapshot import SnapshotError, export_snapshot


def trading_dates(count=430):
    days, day = [], date(2024, 1, 2)
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    return days


def prices(code="000001", count=430, close=100, cap=600_000_000_000):
    return [(code, day, close, close + 1, close - 1, close, 1000, cap, 1_000_000)
            for day in trading_dates(count)]


def pattern_prices(same_day=False):
    rows = prices()
    length = len(rows)
    anchors = [(0, 115), (length - 80, 115.1), (length - 65, 90),
               (length - 55, 108), (length - 45, 75), (length - 35, 108),
               (length - 25, 92), (length - 21, 105), (length - 20, 130 if same_day else 110),
               (length - 18, 130), (length - 1, 130 if same_day else 145)]
    for (start, left), (end, right) in zip(anchors, anchors[1:]):
        for index in range(start, end + 1):
            close = left + (right - left) * (index - start) / (end - start)
            raw = list(rows[index])
            raw[2:6] = [close, close + 1, close - 1, close]
            rows[index] = tuple(raw)
    return rows


class MarketDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # macOS /var is itself a symlink. All supplied trusted roots are canonical.
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source.sqlite"
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE stock_prices (stock_code TEXT, trade_date TEXT, open REAL,
                  high REAL, low REAL, close REAL, volume REAL, market_cap REAL, shares REAL);
                CREATE TABLE companies (stock_code TEXT, corp_name TEXT, market TEXT);
                CREATE TABLE private_notes (secret TEXT);
                INSERT INTO private_notes VALUES ('do not export');
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.source)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def tearDown(self):
        self.temp.cleanup()

    def insert(self, rows, code="000001", name="테스트", market="KOSPI"):
        with self.connect() as connection:
            connection.executemany("INSERT INTO stock_prices VALUES (?,?,?,?,?,?,?,?,?)", rows)
            connection.execute("INSERT INTO companies VALUES (?,?,?)", (code, name, market))

    def snapshot(self, name="snapshot", verified=False, **kwargs):
        output = self.root / name
        export_snapshot(self.source, output, **kwargs)
        if verified:
            # Explicit synthetic provenance, never a production inference.
            path = output / "manifest.json"
            manifest = json.loads(path.read_text())
            manifest["price_adjustment"]["status"] = "adjusted"
            manifest["calendar"]["status"] = "verified"
            manifest["calendar"]["source"] = "synthetic_test_calendar"
            manifest["warnings"] = []
            path.chmod(0o644)
            path.write_text(json.dumps(manifest))
            path.chmod(0o444)
        return output

    def test_export_is_read_only_and_allowlisted(self):
        self.insert(prices(count=40))
        before = self.source.read_bytes()
        with self.connect() as connection:
            logical_before = list(connection.iterdump())
        output = self.snapshot()
        self.assertEqual(before, self.source.read_bytes())
        with self.connect() as connection:
            self.assertEqual(logical_before, list(connection.iterdump()))
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["rows"], 40)
        self.assertEqual(set(pq.read_table(output / "daily.parquet").column_names),
                         {"code", "date", "open", "high", "low", "close", "volume", "mktcap", "shares"})
        self.assertEqual(set(path.name for path in output.iterdir()), {"daily.parquet", "universe.parquet", "manifest.json"})
        self.assertNotIn("do not export", (output / "manifest.json").read_text())
        self.assertNotIn(str(self.source), (output / "manifest.json").read_text())
        for filename, meta in manifest["files"].items():
            self.assertEqual(meta["sha256"], hashlib.sha256((output / filename).read_bytes()).hexdigest())

    def test_ro_connection_and_single_snapshot_during_authorized_writer_commit(self):
        self.insert(prices(count=40))
        writer = sqlite3.connect(self.source)
        writer.execute("PRAGMA journal_mode=WAL")
        real_connect = sqlite3.connect
        arguments, changed = [], []

        def connect(database, **kwargs):
            arguments.append((database, kwargs))
            return real_connect(database, **kwargs)

        def cancel():
            if len(arguments) and not changed:
                # Trigger after first price query established the read transaction.
                writer.execute("UPDATE companies SET corp_name='later commit'")
                writer.execute("UPDATE stock_prices SET close=99")
                writer.commit()
                changed.append(True)
            return False

        try:
            with patch("pipeline.market_analysis.snapshot.sqlite3.connect", side_effect=connect):
                output = self.snapshot(cancel=cancel)
            self.assertTrue(arguments[0][0].endswith("?mode=ro"))
            self.assertTrue(arguments[0][1]["uri"])
            self.assertTrue(changed)
            universe = pq.read_table(output / "universe.parquet").to_pylist()
            daily = pq.read_table(output / "daily.parquet").to_pylist()
            self.assertEqual(universe[0]["name"], "테스트")
            self.assertTrue(all(row["close"] == 100 for row in daily))
            self.assertEqual(writer.execute("SELECT corp_name FROM companies").fetchone()[0], "later commit")
        finally:
            writer.close()

    def test_no_overwrite_symlinks_hardlinks_or_partial_publish(self):
        self.insert(prices(count=40))
        output = self.snapshot()
        with self.assertRaises(SnapshotError):
            export_snapshot(self.source, output)
        linked = self.root / "linked"
        linked.symlink_to(output, target_is_directory=True)
        with self.assertRaises(SnapshotError):
            export_snapshot(self.source, linked / "nested")
        linked_db = self.root / "linked.sqlite"
        linked_db.symlink_to(self.source)
        with self.assertRaises(SnapshotError):
            export_snapshot(linked_db, self.root / "other")
        hardlink = self.root / "hardlink.sqlite"
        os.link(self.source, hardlink)
        with self.assertRaises(SnapshotError):
            export_snapshot(hardlink, self.root / "hardlink-output")
        hardlink.unlink()
        with self.assertRaisesRegex(SnapshotError, "cancelled"):
            export_snapshot(self.source, self.root / "cancelled", cancel=lambda: True)
        self.assertFalse((self.root / "cancelled").exists())
        self.assertEqual(list(self.root.glob(".snapshot-*")), [])

    def test_source_side_effect_helpers_are_not_used(self):
        self.insert(prices(count=40))
        with patch("sqlite3.connect", wraps=sqlite3.connect) as connect:
            self.snapshot()
        self.assertEqual(connect.call_count, 1)
        self.assertNotIn("immutable", connect.call_args.args[0])

    def test_snapshot_as_of_and_orphan_company_are_explicit(self):
        rows = prices(count=40)
        self.insert(rows)
        with self.connect() as connection:
            connection.execute("DELETE FROM companies")
        output = self.snapshot(as_of=rows[20][1])
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["rows"], 21)
        self.assertEqual(manifest["as_of"], rows[20][1])
        self.assertEqual(manifest["quality"]["000001"]["company_status"], "missing")
        self.assertEqual(pq.read_table(output / "universe.parquet").to_pylist()[0]["name"], "000001")

    def test_alphanumeric_krx_codes_are_preserved(self):
        self.insert(prices(code="0001A0", count=60), code="0001A0", name="영문 코드")
        output = self.snapshot(verified=True)
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["rows"], 60)
        self.assertEqual(manifest["excluded"]["invalid_code_or_date_rows"], 0)
        result = screen(output, {"pattern": "none", "require_52w": False})
        self.assertEqual(result["items"][0]["code"], "0001A0")
        self.assertEqual(chart_data(output, "0001A0", {"pattern": "none", "require_52w": False})["code"], "0001A0")

    def test_malformed_identifiers_are_counted_and_warned(self):
        self.insert(prices(count=60))
        self.insert(prices(code="../bad", count=10), code="../bad")
        output = self.snapshot()
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["excluded"]["invalid_code_or_date_rows"], 10)
        self.assertTrue(any("10개 시세 행" in warning for warning in manifest["warnings"]))

    def test_ma_equality_passes_close_but_low_fails(self):
        self.insert(prices(count=60))
        output = self.snapshot(verified=True)
        spec = {"pattern": "none", "require_52w": False}
        result = screen(output, spec)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["counts"]["matched"], 1)
        self.assertEqual(result["items"][0]["ma_value"], 100)
        failed = screen(output, {**spec, "price_basis": "low"})
        self.assertEqual(failed["counts"]["failed"], 1)
        self.assertEqual(failed["counts"]["excluded"], 0)

    def test_one_of_fourteen_ma_breaches_fails(self):
        rows = prices(count=60)
        breach = list(rows[-8])
        breach[2:6] = [70, 71, 69, 70]
        rows[-8] = tuple(breach)
        self.insert(rows)
        result = screen(self.snapshot(verified=True), {"pattern": "none", "require_52w": False})
        self.assertEqual(result["counts"]["matched"], 0)
        self.assertEqual(result["counts"]["failed"], 1)

    def test_unknown_adjustment_is_provisional_and_cannot_be_asserted_by_spec(self):
        self.insert(prices(count=60))
        result = screen(self.snapshot(), {"pattern": "none", "require_52w": False, "price_adjustment": "adjusted"})
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["counts"]["matched"], 1)
        self.assertEqual(result["items"][0]["status"], "provisional")
        self.assertEqual(result["items"][0]["checks"]["price_adjustment"]["status"], "unverified")

    def test_insufficient_and_missing_days_are_not_condition_failures(self):
        rows = prices()
        self.insert(rows)
        sparse = [tuple(["000002", *row[1:]]) for index, row in enumerate(rows) if index != len(rows) - 4]
        self.insert(sparse, code="000002")
        short = [tuple(["000003", *row[1:]]) for row in rows[-20:]]
        self.insert(short, code="000003")
        result = screen(self.snapshot(verified=True), {"pattern": "none", "require_52w": False})
        self.assertEqual(result["counts"], {"universe": 3, "evaluated": 1, "matched": 1,
                                            "excluded": 2, "unevaluated": 2, "failed": 0})
        reasons = {item["code"]: item["reason"] for item in result["excluded"]}
        self.assertEqual(reasons, {"000002": "missing_observed_sessions", "000003": "insufficient_history"})
        self.assertEqual(result["status"], "partial")

    def test_52week_needs_full_year_and_strict_high(self):
        self.insert(prices())
        result = screen(self.snapshot(verified=True), {"pattern": "none", "lookback_days": 10, "require_ma": False})
        self.assertEqual(result["counts"]["failed"], 1)  # Equal high is not a breakout.
        with self.connect() as connection:
            connection.execute("UPDATE stock_prices SET high=103,close=102 WHERE trade_date=?", (trading_dates()[-1],))
        positive = screen(self.snapshot(name="new", verified=True), {"pattern": "none", "lookback_days": 10, "require_ma": False})
        self.assertEqual(positive["counts"]["matched"], 1)
        self.assertEqual(positive["items"][0]["checks"]["high52"]["previous_high"], 101)
        self.assertEqual(positive["items"][0]["checks"]["high52"]["basis"], "close")

    def test_intraday_high_above_52week_high_without_close_breakout_fails(self):
        self.insert(prices())
        with self.connect() as connection:
            connection.execute("UPDATE stock_prices SET high=150 WHERE trade_date=?", (trading_dates()[-1],))
        result = screen(self.snapshot(verified=True), {"pattern": "none", "lookback_days": 10, "require_ma": False})
        self.assertEqual(result["counts"]["failed"], 1)
        self.assertEqual(result["counts"]["matched"], 0)

    def test_compound_pattern_order_ma_and_chart_share_exact_evidence(self):
        self.insert(pattern_prices())
        output = self.snapshot(verified=True)
        result = screen(output, {})
        self.assertEqual(result["counts"]["matched"], 1)
        candidate = result["items"][0]
        self.assertLess(candidate["breakout_date"], candidate["high52_date"])
        self.assertEqual(candidate["pattern"]["pivot_confirmed_at"], trading_dates()[-20])
        chart = chart_data(output, "000001", {})
        marker = next(item for item in chart["markers"] if item["kind"] == "breakout_date")
        self.assertEqual(marker["time"], candidate["breakout_date"])
        self.assertEqual(marker["price"], candidate["pattern"]["breakout_close"])
        self.assertEqual(chart["neckline"][-1]["value"], candidate["pattern"]["breakout_neck"])
        self.assertEqual(chart["ma"][-1]["value"], candidate["ma_value"])
        high_marker = next(item for item in chart["markers"] if item["kind"] == "high52")
        self.assertEqual(high_marker["price"], candidate["checks"]["high52"]["close"])
        json.dumps(result, allow_nan=False)

    def test_pivot_width_30_matches_api_contract(self):
        self.insert(prices())
        result = screen(self.snapshot(verified=True), {"pivot_width": 30, "require_52w": False})
        self.assertEqual(result["spec"]["pivot_width"], 30)

    def test_same_day_high_requires_explicit_flag(self):
        self.insert(pattern_prices(same_day=True))
        output = self.snapshot(verified=True)
        spec = {"require_ma": False}
        self.assertEqual(screen(output, spec)["counts"]["matched"], 0)
        result = screen(output, {**spec, "include_same_day": True})
        self.assertEqual(result["counts"]["matched"], 1)
        self.assertEqual(result["items"][0]["breakout_date"], result["items"][0]["high52_date"])

    def test_high52_after_more_than_fourteen_sessions_still_qualifies(self):
        rows = pattern_prices()
        for index in range(len(rows) - 19, len(rows) - 1):
            raw = list(rows[index])
            raw[2:6] = [112, 113, 111, 112]
            rows[index] = tuple(raw)
        self.insert(rows)
        result = screen(self.snapshot(verified=True), {})
        self.assertEqual(result["counts"]["matched"], 1)
        candidate = result["items"][0]
        days = trading_dates()
        self.assertGreater(days.index(candidate["high52_date"]) - days.index(candidate["breakout_date"]), 14)

    def test_formation_scope_differs_from_breakout_scope(self):
        self.insert(pattern_prices())
        output = self.snapshot(verified=True)
        self.assertEqual(screen(output, {"lookback_days": 30, "window_scope": "breakout"})["counts"]["matched"], 1)
        self.assertEqual(screen(output, {"lookback_days": 30, "window_scope": "formation"})["counts"]["matched"], 0)

    def test_pivot_confirmation_prevents_future_knowledge_claim(self):
        self.insert(pattern_prices())
        output = self.snapshot(verified=True)
        spec = {"pivot_width": 7, "require_ma": False}
        result = screen(output, spec)
        self.assertEqual(result["counts"]["matched"], 1)
        pattern = result["items"][0]["pattern"]
        self.assertTrue(pattern["retrospective"])
        self.assertGreater(pattern["known_at"], pattern["breakout_date"])
        before_confirmation = screen(output, {**spec, "as_of": trading_dates()[-19]})
        self.assertEqual(before_confirmation["counts"]["matched"], 0)

    def test_short_history_never_satisfies_52weeks(self):
        rows = prices(count=120)
        raw = list(rows[-1])
        raw[3] = 1000
        rows[-1] = tuple(raw)
        self.insert(rows)
        result = screen(self.snapshot(verified=True), {"pattern": "none", "require_ma": False})
        self.assertEqual(result["counts"]["evaluated"], 0)
        self.assertEqual(result["counts"]["matched"], 0)
        self.assertEqual(result["excluded"][0]["reason"], "insufficient_history")

    def test_market_cap_is_exact_as_of_never_stale(self):
        rows = prices(count=60)
        raw = list(rows[-1])
        raw[7] = None
        rows[-1] = tuple(raw)
        self.insert(rows)
        result = screen(self.snapshot(verified=True), {"pattern": "none", "require_52w": False})
        self.assertEqual(result["counts"]["matched"], 0)
        self.assertEqual(result["excluded"][0]["reason"], "missing_market_cap")

    def test_bad_candles_and_hash_tampering_are_rejected(self):
        rows = prices(count=60)
        bad = list(rows[-1])
        bad[4] = 0
        rows[-1] = tuple(bad)
        self.insert(rows)
        output = self.snapshot(verified=True)
        result = screen(output, {"pattern": "none", "require_52w": False})
        self.assertEqual(result["excluded"][0]["reason"], "invalid_ohlcv")
        daily = output / "daily.parquet"
        daily.chmod(0o644)
        daily.write_bytes(daily.read_bytes() + b"tamper")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            screen(output, {})


if __name__ == "__main__":
    unittest.main()
