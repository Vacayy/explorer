"""한국 확인 신호 — 수출 3개월 YoY·상태, 공시 창 집계, 원천 방향과 일치 수."""
import sqlite3
import unittest
from datetime import date

from pipeline.kr_confirm import COUNTED, HS_MAP, _dir, disclosure_signal, trade_signal


def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE trade_stats (hs_code TEXT, period TEXT, export_usd REAL);
        CREATE TABLE companies (corp_code TEXT, stock_code TEXT);
        CREATE TABLE disclosures (corp_code TEXT, report_nm TEXT, rcept_dt TEXT, dart_url TEXT);
        INSERT INTO companies VALUES ('C1', '000001');
    """)
    return c


class TradeTests(unittest.TestCase):
    def test_three_month_yoy_and_acceleration(self):
        c = db()
        for m in range(1, 13):
            c.execute("INSERT INTO trade_stats VALUES ('X', ?, 100)", (f"2025-{m:02d}",))
        for m, v in zip(range(1, 10), [110, 110, 110, 110, 110, 110, 150, 150, 150]):
            c.execute("INSERT INTO trade_stats VALUES ('X', ?, ?)", (f"2026-{m:02d}", v))
        s = trade_signal(c, "X")
        self.assertEqual((s["period"], s["yoy_3m"], s["yoy_3m_prev"], s["state"]), ("2026-09", 50.0, 10.0, "가속"))


class DisclosureTests(unittest.TestCase):
    def test_contract_windows_exclude_cancellations(self):
        c = db()
        rows = [("단일판매ㆍ공급계약체결", "20261001"), ("단일판매ㆍ공급계약체결", "20260915"),
                ("단일판매ㆍ공급계약해지", "20260920"), ("단일판매ㆍ공급계약체결", "20260601"),
                ("신규시설투자등", "20260801")]
        c.executemany("INSERT INTO disclosures VALUES ('C1', ?, ?, '')", rows)
        s = disclosure_signal(c, "000001", today=date(2026, 10, 18))
        self.assertEqual((s["contracts_90d"], s["contracts_prev_90d"], s["capex_180d"], s["last_contract"]), (2, 1, 1, "20261001"))
        self.assertEqual(s["direction"], "up")


class DirectionTests(unittest.TestCase):
    def test_state_to_direction(self):
        self.assertEqual(_dir("가속", 10), "up")
        self.assertEqual(_dir("전환↓", -3), "down")
        self.assertEqual(_dir("유지", 25), "up")
        self.assertIsNone(_dir(None, None))

    def test_map_confidence_values(self):
        for code, items in HS_MAP.items():
            for hs, rel, _, conf in items:
                self.assertIn(rel, ("direct", "demand"), code)
                self.assertIn(conf, ("상", "중", "하"), code)
        self.assertEqual(COUNTED, ("상", "중"))


if __name__ == "__main__":
    unittest.main()
