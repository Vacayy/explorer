"""국내 시장 폭(D-321) — 홈 기상도 색 비율의 근거."""
import sqlite3
import unittest

from pipeline.indices import kr_breadth


def _db(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE stock_prices (stock_code TEXT, trade_date TEXT, close INTEGER)")
    conn.executemany("INSERT INTO stock_prices VALUES (?,?,?)", rows)
    return conn


class KrBreadthTest(unittest.TestCase):
    def test_counts_up_down_flat_vs_previous_day(self):
        b = kr_breadth(_db([
            ("A", "2026-11-03", 100), ("A", "2026-11-04", 110),
            ("B", "2026-11-03", 100), ("B", "2026-11-04", 90),
            ("C", "2026-11-03", 100), ("C", "2026-11-04", 120),
            ("D", "2026-11-03", 100), ("D", "2026-11-04", 100),
            ("E", "2026-11-04", 50),  # 전일 종가 없음 → 제외
        ]))
        self.assertEqual((b["trade_date"], b["prev_date"]), ("2026-11-04", "2026-11-03"))
        self.assertEqual((b["up"], b["down"], b["flat"]), (2, 1, 1))
        self.assertEqual(b["up_ratio"], round(2 / 3, 4))

    def test_skips_partially_collected_latest_day(self):
        rows = [(c, "2026-11-02", 100) for c in "ABCD"] + [(c, "2026-11-03", 90) for c in "ABCD"]
        rows.append(("A", "2026-11-04", 200))  # 한 종목만 들어온 날은 비교하지 않는다
        b = kr_breadth(_db(rows))
        self.assertEqual((b["trade_date"], b["prev_date"]), ("2026-11-03", "2026-11-02"))
        self.assertEqual((b["up"], b["down"], b["up_ratio"]), (0, 4, 0.0))

    def test_none_without_two_days_or_moves(self):
        self.assertIsNone(kr_breadth(_db([])))
        self.assertIsNone(kr_breadth(_db([("A", "2026-11-04", 1)])))
        self.assertIsNone(kr_breadth(_db([("A", "2026-11-03", 5), ("A", "2026-11-04", 5)])))


if __name__ == "__main__":
    unittest.main()
