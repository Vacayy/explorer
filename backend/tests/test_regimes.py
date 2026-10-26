"""국면 이력 규칙(docs/specs/market-regimes.md) — 가상 종가로 Lunde–Timmermann 20/20·조정·10개월선을 고정한다."""
import unittest
from datetime import date, timedelta

from pipeline.regimes import corrections_of, phases_of, trend_of, turning_points


def series(values, start=date(2000, 1, 3), step=1):
    return [((start + timedelta(days=i * step)).isoformat(), float(v)) for i, v in enumerate(values)]


class TurningPoints(unittest.TestCase):
    def test_bear_confirmed_at_minus_20(self):
        closes = [100, 110, 120, 100, 96, 90, 110]   # 120 → 96 = −20% (확정), 저점 90 → 110 = +22% (확정)
        self.assertEqual(turning_points(closes), [("trough", 0, 2), ("peak", 2, 4), ("trough", 5, 6)])  # 시작 100→120 +20%로 첫 저점 확정

    def test_minus_19_is_not_bear(self):
        self.assertEqual(turning_points([100, 115, 93.2, 110]), [])

    def test_phases_and_provisional(self):
        p = phases_of(series([100, 110, 120, 100, 96, 90, 110]))
        self.assertEqual([x["kind"] for x in p], ["bull", "bear", "bull"])   # 첫 극점(0) 이전 구간은 없다
        self.assertEqual(p[1]["confirm_date"], series([0] * 5)[4][0])
        self.assertTrue(p[-1]["provisional"])
        self.assertFalse(p[1]["provisional"])
        self.assertEqual(p[1]["change_pct"], -25.0)

    def test_segment_before_first_turn_is_dropped(self):
        p = phases_of(series([100, 104, 98, 120, 95]))   # 98→120 +22%로 첫 저점(2) 확정 — 0~2는 상태 불명
        self.assertEqual(p[0]["start"], series([0] * 3)[2][0])


class Corrections(unittest.TestCase):
    def test_correction_inside_bull_and_near_threshold(self):
        s = series([100, 120, 107, 98, 121, 130, 116, 131])   # 120→98 = −18.3%(임계 근접, 회복), 130→116 = −10.8%
        c = corrections_of(s, phases_of(s))
        self.assertEqual([(x["drawdown_pct"], x["near_threshold"]) for x in c], [(-18.33, True), (-10.77, False)])
        self.assertEqual(c[0]["end"], s[4][0])


class Trend(unittest.TestCase):
    def test_month_end_vs_10m_sma(self):
        s = series([100 + i for i in range(12)] + [50], start=date(2000, 1, 31), step=31)
        t = trend_of(s)
        self.assertEqual([x["state"] for x in t], ["up", "down"])
        self.assertEqual(t[0]["end"], t[1]["start"])


class EraState(unittest.TestCase):
    """지금 시장 읽기 층 1 — 가격 3종 판정(pipeline/era._price_flags)."""
    def test_all_three_on_in_drawdown(self):
        from pipeline.era import _price_flags
        s = series([100 + i for i in range(300)] + [300 - 3 * i for i in range(40)])   # 오르다 꺾임
        d, c = [x for x, _ in s], [v for _, v in s]
        i = len(c) - 1
        f = _price_flags(d, c, i, list(range(i - 9 * 21, i + 1, 21)))
        self.assertTrue(f["below_10m"]["on"])
        self.assertTrue(f["dd_52w"]["on"])          # 고점 399 → 282, −29%
        self.assertFalse(f["mom_12m"]["on"])        # 1년 전(약 35)보다는 높다

    def test_yoy(self):
        from pipeline.era import _yoy
        m = [(f"{y}-{mo:02d}-01", 100 * (1.03 ** (y - 2020))) for y in (2020, 2021) for mo in (1, 2)]
        self.assertAlmostEqual(_yoy(m)[-1][1], 3.0, places=6)


if __name__ == "__main__":
    unittest.main()
