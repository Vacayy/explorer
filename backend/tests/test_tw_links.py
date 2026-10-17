"""대만 → 한국 연결 근거 — 분기 이동, 시차별 상관·같은 방향 비율 (pipeline/tw_links)."""
import unittest

from pipeline.tw_links import _corr, _shift, evidence


class TwLinksTests(unittest.TestCase):
    def test_shift_quarters(self):
        self.assertEqual(_shift("26.03", 1), "25.12")
        self.assertEqual(_shift("26.06", 2), "25.12")
        self.assertEqual(_shift("25.09", 0), "25.09")

    def test_corr_needs_four_points(self):
        self.assertIsNone(_corr([1, 2, 3], [1, 2, 3]))
        self.assertEqual(_corr([1, 2, 3, 4], [2, 4, 6, 8]), 1.0)

    def test_leading_series_is_best_at_its_lag(self):
        periods = ["24.03", "24.06", "24.09", "24.12", "25.03", "25.06", "25.09", "25.12"]
        tw_vals = [5, 20, -10, 30, 0, 40, -20, 10, 25]
        tw = {p: v for p, v in zip(["23.12"] + periods, tw_vals)}
        kr = {p: tw[_shift(p, 1)] for p in periods}              # 한국 = 대만 1분기 뒤
        ev = evidence(tw, kr)
        self.assertEqual(ev["best_lag"], 1)
        self.assertEqual(ev["by_lag"][1]["corr"], 1.0)
        self.assertEqual(ev["by_lag"][1]["same_dir"], 1.0)


if __name__ == "__main__":
    unittest.main()


class TwSignalTests(unittest.TestCase):
    """연결 회사 합계의 3개월 YoY와 3개월 전 대비 상태"""
    def setUp(self):
        import sqlite3
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE tw_monthly_revenue (code TEXT, ym TEXT, revenue REAL, last_year REAL)")

    def fill(self, yoys):
        for i, y in enumerate(yoys):
            ym = f"2026-{i + 1:02d}"
            self.conn.execute("INSERT INTO tw_monthly_revenue VALUES ('A', ?, ?, 100)", (ym, 100 + y))

    def test_acceleration(self):
        from pipeline.tw_links import tw_signal
        self.fill([10, 10, 10, 30, 30, 30])
        s = tw_signal(self.conn, ["A"])
        self.assertEqual((s["yoy_3m_prev"], s["yoy_3m"], s["state"]), (10.0, 30.0, "가속"))

    def test_turn_down(self):
        from pipeline.tw_links import tw_signal
        self.fill([5, 5, 5, -5, -5, -5])
        self.assertEqual(tw_signal(self.conn, ["A"])["state"], "전환↓")

    def test_steady(self):
        from pipeline.tw_links import tw_signal
        self.fill([20, 20, 20, 25, 25, 25])
        self.assertEqual(tw_signal(self.conn, ["A"])["state"], "유지")


class TwAdapterTests(unittest.TestCase):
    def test_parse_refs(self):
        from pipeline.proxy_adapters import _tw_parse
        self.assertEqual(_tw_parse("2330:yoy3m")[0], ["2330"])
        self.assertEqual(_tw_parse("2330")[2], None)
        self.assertGreater(len(_tw_parse("layer:server:yoy")[0]), 5)
        self.assertIsNone(_tw_parse("9999"))
        self.assertIsNone(_tw_parse("2330:bad"))
