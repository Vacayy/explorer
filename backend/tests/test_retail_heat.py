"""개인 투자 열기 (D-231) — 증가율·백분위(미래 정보 없음)·국면 규칙·스냅샷. 값은 모두 가상."""
import sqlite3
import unittest
from datetime import date, timedelta
from unittest import mock

from pipeline import retail_heat as rh


def db(days=900, credit_step=1.0):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    rh.ensure_schema(c)
    d0 = date(2020, 1, 1)
    for i in range(days):
        c.execute("INSERT INTO retail_flows (date, credit_total, deposits, kospi_close, kospi_value, kosdaq_value, kospi_cap, kosdaq_cap) "
                  "VALUES (?,?,?,?,?,?,?,?)",
                  ((d0 + timedelta(days=i)).isoformat(), 100 + i * credit_step, 50 + (i % 7), 2000, 10, 5, 1000, 500))
    c.commit()
    return c


class RetailTests(unittest.TestCase):
    def test_percentile_uses_only_the_past(self):
        pts = [{"x": float(v)} for v in range(600)] + [{"x": -1.0}]
        out = rh.with_percentiles(pts, keys=["x"])
        self.assertIsNone(out[10]["x_pct"])                       # 2년(500일) 미만 이력
        self.assertEqual(out[599]["x_pct"], 100.0)                  # 과거 최대보다 큼
        self.assertEqual(out[-1]["x_pct"], 0.0)

    def test_sliding_window_drops_old_values(self):
        pts = [{"x": 1000.0}] * 10 + [{"x": float(v)} for v in range(1400)]
        out = rh.with_percentiles(pts, keys=["x"])
        self.assertEqual(out[-1]["x_pct"], 100.0)                   # 초기 1000들은 5년 창 밖으로 밀려남

    def test_series_growth_leverage_turnover(self):
        p = rh.series(db(60))[-1]
        self.assertAlmostEqual(p["credit_growth"], 20 / 139)       # (159 − 139) / 139
        self.assertAlmostEqual(p["leverage"], 159 / 1500)
        self.assertAlmostEqual(p["turnover"], 20 * 15 / 1500)
        self.assertAlmostEqual(p["value_growth"], 0.0)

    def test_regime_rules(self):
        base = {"credit_growth": 0.02, "value_growth": 0.01, "kospi_return": 0.0, "credit_growth_pct": 50, "value_growth_pct": 50, "deposit_growth_pct": 50}
        self.assertEqual(rh.classify(base)["key"], "neutral")
        self.assertEqual(rh.classify({**base, "kospi_return": -0.08, "credit_growth": -0.05, "credit_growth_pct": 5})["key"], "deleveraging")
        self.assertEqual(rh.classify({**base, "credit_growth_pct": 85, "deposit_growth_pct": 40})["key"], "leverage_led")
        self.assertEqual(rh.classify({**base, "value_growth_pct": 90, "deposit_growth_pct": 30, "credit_growth": 0.0})["key"], "churn")
        self.assertEqual(rh.classify({**base, "credit_growth_pct": 70, "value_growth_pct": 75, "deposit_growth_pct": 65,
                                      "credit_growth": 0.01, "value_growth": 0.03})["key"], "broad_inflow")
        self.assertTrue(rh.classify(base)["reasons"])

    def test_summary_and_snapshots_without_krx(self):
        c = db(900)
        with mock.patch.object(rh, "EPISODES", [("t", "가상 구간", "2021-06-01", "2022-01-01")]), mock.patch.dict("os.environ", {}, clear=True):
            n = rh.save_snapshots(c)
            s = rh.summary(c)
            snaps = rh.snapshots(c)
        self.assertEqual(n, 1)
        self.assertFalse(s["krx_configured"])
        self.assertIn(s["regime"]["key"], rh.REGIMES)
        self.assertIsNone(next(m for m in s["metrics"] if m["key"] == "indiv_share")["value"])   # 한국거래소 없으면 비움
        self.assertEqual(snaps[0]["name"], "가상 구간")


    def test_krx_login_failure_is_reported_not_silent(self):
        c = db(30)
        with mock.patch.dict("os.environ", {"KRX_ID": "가상", "KRX_PW": "가상"}), \
                mock.patch.object(rh, "collect_kofia", lambda conn, s, e: 0), \
                mock.patch.object(rh, "_krx_logged_in", lambda: False):
            r = rh.collect(c)
        self.assertIn("로그인 실패", r["krx_error"])


if __name__ == "__main__":
    unittest.main()