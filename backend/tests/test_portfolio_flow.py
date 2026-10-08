"""포트폴리오 자료 흐름 판정 (portfolio-intelligence §3)."""
import unittest
from datetime import date

from pipeline import portfolio_flow as fl


def series(counts, negs=None):
    negs = negs or [0] * len(counts)
    return [{"date": f"d{i}", "n": n, "pos": 0, "neg": g} for i, (n, g) in enumerate(zip(counts, negs))]


class FlowTests(unittest.TestCase):
    def test_surge_needs_floor_and_multiple(self):
        self.assertTrue(fl.judge(series([1] * 7 + [3]))["surge"])
        self.assertFalse(fl.judge(series([0] * 7 + [2]))["surge"])         # 3건 미만
        self.assertFalse(fl.judge(series([8] * 7 + [11]))["surge"])        # 2배 미만

    def test_tone_shift(self):
        self.assertTrue(fl.judge(series([2] * 7 + [3], [0] * 7 + [2]))["tone_shift"])
        self.assertFalse(fl.judge(series([2] * 7 + [1], [0] * 7 + [1]))["tone_shift"])   # 오늘 1건은 판정 안 함

    def test_summary_lines_only_when_notable(self):
        today = date(2026, 1, 8)
        quiet = {"name": "가", "surge": False, "tone_shift": False, "today": 1, "avg7": 1, "neg_today_pct": 0, "neg_prev_pct": 0,
                 "digest": {"date": "2026-01-07", "insights": "어제 것"}}
        new = {**quiet, "name": "나", "digest": {"date": "2026-01-08", "insights": "수주 공시로 시각 전환"}}
        surge = {**quiet, "name": "다", "surge": True, "today": 6, "avg7": 1.2, "digest": None}
        self.assertEqual(fl.summary_lines([quiet, new, surge], today),
                         ["· 나: 수주 공시로 시각 전환", "· 다: 언급 급증 6건(7일 평균 1.2)"])


if __name__ == "__main__":
    unittest.main()
