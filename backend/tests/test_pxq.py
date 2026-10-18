"""P×Q 분해 — 금액 = 단가 × 물량, 판정(가격·물량 주도·동반·역행)."""
import math
import sqlite3
import unittest

from pipeline.pxq import classify, decompose


class PxqTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify(0.5, 0.05), "가격 주도")
        self.assertEqual(classify(0.02, 0.4), "물량 주도")
        self.assertEqual(classify(0.2, 0.15), "동반")
        self.assertEqual(classify(0.3, -0.1), "역행")
        self.assertEqual(classify(-0.017, 0.227), "물량 주도")     # 단가 −1.7%는 사실상 정체
        self.assertEqual(classify(0.01, -0.02), "정체")

    def test_decompose_identity(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute("CREATE TABLE trade_stats (hs_code TEXT, period TEXT, export_usd REAL, export_wt REAL)")
        for m in range(1, 13):
            c.execute("INSERT INTO trade_stats VALUES ('X', ?, 100, 10)", (f"2025-{m:02d}",))
        for m in range(1, 4):
            c.execute("INSERT INTO trade_stats VALUES ('X', ?, 180, 12)", (f"2026-{m:02d}",))   # 금액 +80%, 물량 +20% → 단가 +50%
        d = decompose(c, "X")
        self.assertEqual((d["period"], d["value_yoy"], d["qty_yoy"], d["price_yoy"]), ("2026-03", 80.0, 20.0, 50.0))
        self.assertEqual(d["verdict"], "가격 주도")
        self.assertEqual(d["price_share"], round(math.log(1.5) / math.log(1.8) * 100))


if __name__ == "__main__":
    unittest.main()
