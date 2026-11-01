"""수출입 데이터 위생 — 라벨 오기·번호 접미 중복명·상위/하위 HS 이중 집계 (조사 D, 2026-10-16).

하이라이트 2위가 '총수출 +532%'(실제는 D램 세목)였고, 854232(메모리)와 그 하위 8542321010을 함께 더해
분류 합계·기여도 분모가 이중으로 셌다.
"""
import sqlite3
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from pipeline import trade, trade_metrics
from routers import spine_trade
from tests.test_job_status import KeepOpen


def _months(n: int, start=(2024, 1)):
    y, m = start
    for _ in range(n):
        yield f"{y}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


class CleanNameTests(unittest.TestCase):
    def test_known_mislabel_and_suffixes(self):
        self.assertEqual(trade.clean_item_name("8542321010", "총수출"), "D램")
        self.assertEqual(trade.clean_item_name("3921192010", "분리막(2)"), "분리막")
        self.assertEqual(trade.clean_item_name("8524923000", "OLDE패널(TV) (2)"), "OLED패널(TV)")
        # 괄호 속 설명은 번호가 아니므로 남긴다
        self.assertEqual(trade.clean_item_name("8524121000", "OLDE패널(휴대용 10키로미만)"), "OLED패널(휴대용 10키로미만)")


class TradeDbCase(unittest.TestCase):
    def setUp(self):
        raw = sqlite3.connect(":memory:", check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.executescript("""
            CREATE TABLE trade_follow(hs_code TEXT PRIMARY KEY, item_name TEXT, group_label TEXT, active INTEGER DEFAULT 1);
            CREATE TABLE trade_stats(hs_code TEXT, period TEXT, export_usd REAL, import_usd REAL, export_wt REAL,
                import_wt REAL, balance_usd REAL, UNIQUE(hs_code, period));
            CREATE TABLE trade_beneficiaries(hs_code TEXT, stock_code TEXT, name TEXT, rel TEXT, reason TEXT);
        """)
        self.conn = KeepOpen(raw)


class NormalizeLabelTests(TradeDbCase):
    def test_suffix_collisions_get_hs_and_mislabel_moves_group(self):
        self.conn.executemany("INSERT INTO trade_follow(hs_code, item_name, group_label) VALUES (?,?,?)", [
            ("3921191010", "분리막(1)", "2차전지"), ("3921192010", "분리막(2)", "2차전지"),
            ("8542321010", "총수출", "전자부품"), ("3002491000", "보톡스", "바이오·의료")])
        self.assertEqual(trade.normalize_labels(self.conn), 3)
        got = {r["hs_code"]: (r["item_name"], r["group_label"]) for r in self.conn.execute("SELECT * FROM trade_follow")}
        self.assertEqual(got["3921191010"][0], "분리막 · 3921191010")
        self.assertEqual(got["3921192010"][0], "분리막 · 3921192010")
        self.assertEqual(got["8542321010"], ("D램", "반도체"))
        self.assertEqual(got["3002491000"][0], "보톡스")
        self.assertEqual(trade.normalize_labels(self.conn), 0)   # 멱등


class NestedTotalsTests(TradeDbCase):
    def setUp(self):
        super().setUp()
        self.conn.executemany("INSERT INTO trade_follow(hs_code, item_name, group_label) VALUES (?,?,?)", [
            ("854232", "메모리", "반도체"), ("8542321010", "D램", "반도체"), ("2710", "석유제품", "에너지")])
        rows = []
        for i, p in enumerate(_months(24)):
            # 마지막 달만 3배(급등). 앞 달은 z가 나오도록 약간 흔든다(MAD 0 방지). 석유는 전년 동월과 같게.
            k = 3.0 if i == 23 else 1 + 0.02 * (i % 5)
            rows += [("854232", p, 100e6 * k), ("8542321010", p, 60e6 * k), ("2710", p, 50e6)]
        self.conn.executemany("INSERT INTO trade_stats(hs_code, period, export_usd) VALUES (?,?,?)", rows)
        self.conn.execute("INSERT INTO trade_beneficiaries VALUES ('8542321010','000660','SK하이닉스','수혜','D램 수출')")

    def test_child_excluded_from_group_total_and_contribution_denominator(self):
        with patch.object(trade_metrics, "get_connection", return_value=self.conn):
            t = trade_metrics.table()
            h = trade_metrics.highlights()
        by = {r["hs_code"]: r for r in t["rows"]}
        self.assertEqual(by["8542321010"]["nested_in"], "854232")
        self.assertIsNone(by["854232"]["nested_in"])
        semi = next(g for g in t["groups"] if g["group_label"] == "반도체")
        self.assertAlmostEqual(semi["value"], 300e6)               # 메모리만 — D램(180M)을 또 더하지 않는다
        self.assertAlmostEqual(by["854232"]["contribution"], 1.0)   # 분모 = 최상위 Δ 합(메모리 +200M, 석유 0)
        self.assertAlmostEqual(by["8542321010"]["contribution"], 0.6)
        self.assertAlmostEqual(h["total_usd"], 350e6)

    def test_stock_reverse_link(self):
        with patch.object(trade_metrics, "get_connection", return_value=self.conn), \
                patch.object(spine_trade, "get_connection", return_value=self.conn):
            got = TestClient(app).get("/api/spine/trade/by-stock/000660").json()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["item_name"], "D램")
        self.assertEqual(got[0]["rel"], "수혜")
        self.assertEqual(got[0]["flag"], "surge")
        self.assertEqual(got[0]["period"], "2025-12")


if __name__ == "__main__":
    unittest.main()
