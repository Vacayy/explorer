"""기술적 읽기 층(D-198): 문장은 판정만 서술하고, 캔버스 규칙은 순서대로, 같은 입력은 같은 출력."""
import re
import unittest

from pipeline import technical_scan as ts
from pipeline.technical_commentary import price_context
from pipeline.technical_reading import GROUPS, canvas, readings

FORBIDDEN = re.compile(r"(?<!과)매수|(?<!과)매도|추천|유망|전망|오를|내릴|상승할|하락할")


def bars(closes, start=(2025, 1, 1), volume=1000.0):
    from datetime import date, timedelta
    first = date(*start)
    return [{"date": (first + timedelta(days=i)).isoformat(), "open": float(c), "high": float(c) + 1, "low": float(c) - 1, "close": float(c), "volume": volume, "shares": 1000.0}
            for i, c in enumerate(closes)]


class Readings(unittest.TestCase):
    def setUp(self):
        # 300봉: 완만한 상승 뒤 마지막 20봉 박스. 모든 계열이 평가 가능한 길이.
        closes = [100 + i * 0.3 for i in range(280)] + [184 + (2 if i % 2 else -2) for i in range(20)]
        self.rows = bars(closes)
        self.scan = ts.scan_rows(self.rows, within=5)
        self.price = price_context(self.rows)

    def test_five_sentences_in_group_order_with_valid_basis(self):
        out = readings(self.scan, self.price)
        self.assertEqual([r["group"] for r in out], [g for g, _ in GROUPS])
        known = {e["id"] for e in self.scan["states"] + self.scan["signals"] + self.scan["unavailable"]} | {f"price.{k}" for k in self.price}
        for reading in out:
            self.assertTrue(reading["text"].endswith("."), reading)
            self.assertIsNone(FORBIDDEN.search(reading["text"]), reading["text"])
            for identifier in reading["basis"]:
                self.assertIn(identifier, known, identifier)
        trend = next(r for r in out if r["group"] == "추세·모멘텀")
        self.assertIn("1년 수익률", trend["text"])
        self.assertIn("200일선 위", trend["text"])
        reversion = next(r for r in out if r["group"] == "평균회귀")
        self.assertIn("RSI", reversion["text"])
        self.assertIn("볼린저 밴드", reversion["text"])
        self.assertEqual(readings(self.scan, self.price), out)

    def test_short_history_says_unavailable_instead_of_guessing(self):
        scan = ts.scan_rows(bars([100 + i for i in range(40)]), within=5)
        out = {r["group"]: r for r in readings(scan, price_context(bars([100 + i for i in range(40)])))}
        self.assertIn("이력이 부족", out["추세·모멘텀"]["text"])
        self.assertEqual(out["추세·모멘텀"]["basis"], [])

    def test_empty_scan_has_no_readings_or_canvas_payload(self):
        scan = ts.scan_rows([], within=5)
        self.assertEqual(len(readings(scan, {})), 5)
        self.assertEqual(canvas(scan)["kind"], "levels")


class Canvas(unittest.TestCase):
    def make(self, states=(), signals=()):
        return {"within": 5, "states": [{"id": i, "status": "pass", "label": i, "value": 1, "reference": 1} for i in states],
                "signals": [{"id": i, "status": "pass", "label": i, "date": "2026-09-18", "category": "가격 구조"} for i in signals], "unavailable": []}

    def test_rules_apply_in_order(self):
        self.assertEqual(canvas(self.make(states=["trading_range"], signals=["channel_break_up"]))["kind"], "levels")
        self.assertEqual(canvas(self.make(signals=["channel_break_up"]))["kind"], "channel")
        self.assertEqual(canvas(self.make(states=["higher_lows"]))["kind"], "trendline_low")
        self.assertEqual(canvas(self.make(signals=["trendline_break_up"]))["kind"], "trendline_high")
        self.assertEqual(canvas(self.make(signals=["false_breakdown"]))["window"], "1y")
        self.assertEqual(canvas(self.make(signals=["volume_profile_up_60d"]))["kind"], "profile")
        default = canvas(self.make())
        self.assertEqual((default["kind"], default["window"], default["swing"], default["fit"], default["basis"]), ("levels", "1y", 5, "two_point", []))
        self.assertTrue(default["reason"])


if __name__ == "__main__":
    unittest.main()
