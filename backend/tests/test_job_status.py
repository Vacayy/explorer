"""잡 실행 기록이 실제 결과를 따른다 — 예외 없이 끝나도 실패는 실패로 남긴다.

2026-10-15 저녁 prices 잡은 3,975종목 전부 ConnectionError였는데 job_runs에는 ok로 남았다.
"""
import importlib.util
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import ops

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class KeepOpen:
    """스크립트가 close()해도 테스트가 같은 메모리 DB를 계속 보도록."""
    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


class RunJobStatusTests(unittest.TestCase):
    def run_with(self, result):
        with patch.object(ops, "flag_enabled", return_value=True), patch.object(ops, "record_run") as rec:
            ops.run_job("x", lambda: result)
        return rec.call_args.args[1]

    def test_returned_status_is_recorded(self):
        self.assertEqual(self.run_with({"status": "error", "failed": 3}), "error")
        self.assertEqual(self.run_with({"status": "partial"}), "partial")

    def test_plain_results_stay_ok(self):
        self.assertEqual(self.run_with({"upsert": 10}), "ok")
        self.assertEqual(self.run_with(None), "ok")
        self.assertEqual(self.run_with({"status": "stale"}), "ok")  # 브리핑의 stale은 데이터 기준일 표시라 실패가 아니다


class DailyPricesStatusTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_script("ingest_prices")
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE companies(stock_code TEXT);
            CREATE TABLE stock_prices(stock_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL,
                                      volume REAL, market_cap REAL, shares REAL, PRIMARY KEY(stock_code, trade_date));
        """)
        self.conn.executemany("INSERT INTO companies VALUES (?)", [(f"{i:06d}",) for i in range(450)])
        self.conn = KeepOpen(self.conn)

    def test_all_batches_failing_is_an_error(self):
        import requests
        with patch.object(self.mod, "get_connection", return_value=self.conn), \
             patch.object(requests, "get", side_effect=requests.ConnectionError("down")), \
             patch.object(self.mod.time, "sleep"):
            r = self.mod.ingest_daily(repair_days=0)
        self.assertEqual(r["failed"], 450)
        self.assertEqual(r["status"], "error")


if __name__ == "__main__":
    unittest.main()
