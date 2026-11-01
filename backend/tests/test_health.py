"""데이터 신선도 점검 — 거래일 지연·휴장일·저장 종목 수·경과 시간 (D-222)."""
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from pipeline import health

KST = timezone(timedelta(hours=9))
# 10-09(한글날)는 휴장 — 지수 달력에 없다
DAYS = ["2026-10-06", "2026-10-07", "2026-10-08", "2026-10-12", "2026-10-13"]


def at(day: str, hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm[:2]}:{hhmm[2:]}:00").replace(tzinfo=KST)


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript("""
            CREATE TABLE market_indicators(snapshot_date TEXT, indicator TEXT, value REAL);
            CREATE TABLE stock_prices(stock_code TEXT, trade_date TEXT, market_cap REAL);
            CREATE TABLE watch_evaluations(as_of TEXT); CREATE TABLE kr_movers(trade_date TEXT);
            CREATE TABLE raw_documents(source_type TEXT, fetched_at TEXT);
            CREATE TABLE job_runs(job TEXT, status TEXT, ran_at TEXT); CREATE TABLE us_briefings(created_at TEXT);
        """)
        self.conn.executemany("INSERT INTO market_indicators VALUES (?, 'index_kospi', 1)", [(d,) for d in DAYS])

    def prices(self, day: str, n: int, caps: int | None = None):
        caps = n if caps is None else caps
        self.conn.executemany("INSERT INTO stock_prices VALUES (?, ?, ?)", [(f"{i:06d}", day, 1e11 if i < caps else None) for i in range(n)])

    def test_holiday_is_not_counted_and_today_waits_for_close(self):
        self.assertEqual(health.expected_trading_day(self.conn, "1730", at("2026-10-13", "1500")), "2026-10-12")
        self.assertEqual(health.expected_trading_day(self.conn, "1730", at("2026-10-13", "1800")), "2026-10-13")
        self.assertEqual(health.trading_lag(self.conn, "2026-10-08", "2026-10-12"), 1)  # 10-09 휴장 제외
        self.assertEqual(health.trading_lag(self.conn, "2026-10-13", "2026-10-13"), 0)

    def test_partial_daily_prices_are_stale_even_when_the_date_is_current(self):
        for day in DAYS[:3]:
            self.prices(day, 2870)
        self.prices("2026-10-12", 105)  # 10-12: marketStatus OPEN으로 105종목만 저장된 날
        with patch.object(health, "launchd_failures", return_value=[]), patch.object(health, "_history_as_of", return_value=None):
            item = next(i for i in health.report(self.conn, at("2026-10-12", "1800")) if i["key"] == "prices")
        self.assertEqual(item["status"], "stale")
        self.assertIn("105종목", item["detail"])

    def test_missing_market_caps_on_the_latest_day_are_stale(self):
        for day in DAYS[:3]:
            self.prices(day, 2870)
        self.prices("2026-10-12", 2755, caps=105)  # yfinance 보충분은 시총이 비어 있었다
        with patch.object(health, "launchd_failures", return_value=[]), patch.object(health, "_history_as_of", return_value=None):
            item = next(i for i in health.report(self.conn, at("2026-10-12", "1800")) if i["key"] == "prices")
        self.assertEqual(item["status"], "stale")
        self.assertIn("시가총액 105/2,755", item["detail"])

    def test_age_checks_and_alerts_only_carry_critical_items(self):
        now = at("2026-10-13", "1800")
        self.conn.execute("INSERT INTO raw_documents VALUES ('telegram', '2026-10-11 00:00:00')")
        with patch.object(health, "launchd_failures", return_value=["chain(종료 1)"]), patch.object(health, "_history_as_of", return_value=None):
            items = health.report(self.conn, now)
        status = {i["key"]: i for i in items}
        self.assertEqual(status["documents"]["status"], "stale")
        self.assertEqual(status["launchd"]["status"], "stale")
        lines = health.alerts(items)
        self.assertTrue(any(line.startswith("피드 문서 유입") for line in lines))
        self.assertFalse(any("예약 작업" in line for line in lines))  # 비중요 항목은 관리자 화면에만

    def test_kr_dossier_sources_flag_stale_valuation_and_disclosures(self):
        self.conn.executescript("""
            CREATE TABLE fundamentals(stock_code TEXT, trade_date TEXT);
            CREATE TABLE disclosures(rcp_no TEXT, rcept_dt TEXT);
            INSERT INTO fundamentals VALUES ('005930', '2026-09-07');
            INSERT INTO disclosures VALUES ('1', '20260916');
        """)
        with patch.object(health, "launchd_failures", return_value=[]), patch.object(health, "_history_as_of", return_value=None):
            status = {i["key"]: i for i in health.report(self.conn, at("2026-10-13", "2340"))}
        self.assertEqual(status["kr_valuation"]["status"], "stale")   # 09-07에 멈춘 밸류(2026-10-16 실측)
        self.assertEqual(status["kr_disclosures"]["status"], "stale")
        self.assertEqual(status["kr_financials"]["detail"], "저장된 데이터 없음")
        self.conn.execute("INSERT INTO fundamentals VALUES ('005930', '2026-10-13')")
        self.conn.execute("INSERT INTO disclosures VALUES ('2', '20261013')")
        with patch.object(health, "launchd_failures", return_value=[]), patch.object(health, "_history_as_of", return_value=None):
            status = {i["key"]: i for i in health.report(self.conn, at("2026-10-13", "2340"))}
        self.assertEqual(status["kr_valuation"]["status"], "ok")
        self.assertEqual(status["kr_disclosures"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
