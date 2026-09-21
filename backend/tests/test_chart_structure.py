"""차트 구조 그리기 — 채널·추세선 계산과 질문 해석 규칙 (D-195)."""
import sqlite3
import unittest

from pipeline import chart_structure as cs


def rows(n=120, slope=0.2, base=100.0, amp=6.0, period=20):
    """상승 채널 합성(세션당 0.2): 고점이 20봉마다 base+slope*i+amp, 저점이 base+slope*i-amp."""
    out = []
    for i in range(n):
        phase = i % period
        mid = base + slope * i
        high = mid + (amp if phase == 10 else amp * 0.5)
        low = mid - (amp if phase == 0 else amp * 0.5)
        out.append({"date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "open": mid, "high": high, "low": low, "close": mid + (0.3 if phase % 2 else -0.3), "volume": 1000})
    return out


class Structure(unittest.TestCase):
    def test_channel_two_point_connects_highest_highs_and_lower_touches_min_low(self):
        r = rows()
        out = cs.structure(r, "channel", 5)
        self.assertEqual(out["swing"], 5)
        upper, lower = out["lines"]
        self.assertEqual([l["id"] for l in out["lines"]], ["channel:upper", "channel:lower"])
        # 상단선 기울기 = 합성 기울기(세션당 0.2)
        dx = len(r) - 1 - r.index(next(x for x in r if x["date"] == upper["points"][0]["time"]))
        slope = (upper["points"][1]["value"] - upper["points"][0]["value"]) / dx
        self.assertAlmostEqual(slope, 0.2, places=6)
        anchors = [p for p in out["pivots"] if p["anchor"]]
        self.assertEqual(len(anchors), 2)
        self.assertTrue(all(p["side"] == "high" for p in out["pivots"]))
        # 하단선은 기간 안 가장 낮은 저가에 닿는다(그 아래로 내려가는 저가 없음)
        start = r.index(next(x for x in r if x["date"] == upper["points"][0]["time"]))
        a = lower["points"][0]["value"]
        for i in range(start, len(r)):
            self.assertGreaterEqual(r[i]["low"] + 1e-6, a + slope * (i - start))
        self.assertTrue(0 <= out["summary"]["position_pct"] <= 100)
        self.assertGreaterEqual(out["summary"]["touches_upper"], 2)
        self.assertEqual(out["notes"], [])

    def test_trendlines_pick_extreme_then_next_extreme(self):
        out = cs.structure(rows(), "trendline_high", 5)
        self.assertEqual(out["lines"][0]["id"], "trendline_high")
        self.assertEqual(sum(p["anchor"] for p in out["pivots"]), 2)
        low = cs.structure(rows(), "trendline_low", 5)
        self.assertTrue(all(p["side"] == "low" for p in low["pivots"]))
        self.assertIsNotNone(low["summary"]["distance_pct"])

    def test_swing_relaxes_until_two_pivots_then_gives_up(self):
        out = cs.structure(rows(n=60), "channel", 25)  # 60봉에 폭 25면 스윙 불가 → 완화
        self.assertLess(out["swing"], 25)
        self.assertEqual(out["requested_swing"], 25)
        self.assertTrue(out["notes"] and "줄여" in out["notes"][0])
        flat = [{"date": f"2026-01-{d:02d}", "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1} for d in range(1, 12)]
        with self.assertRaises(cs.StructureUnavailable):
            cs.structure(flat, "channel", 3)
        with self.assertRaises(cs.StructureUnavailable):
            cs.structure(rows(), "channel", 1)

    def test_regression_uses_all_pivots(self):
        out = cs.structure(rows(), "channel", 5, "regression")
        self.assertEqual(sum(p["anchor"] for p in out["pivots"]), len(out["pivots"]))

    def test_window_bounds(self):
        self.assertEqual(cs.window_bounds("ytd", "2026-09-18"), ("2026-01-01", "2026-09-18"))
        self.assertEqual(cs.window_bounds("6m", "2026-09-18")[0], "2026-03-22")
        self.assertEqual(cs.window_bounds("2026-02-01:2026-05-01", "2026-09-18"), ("2026-02-01", "2026-05-01"))
        with self.assertRaises(cs.StructureUnavailable):
            cs.window_bounds("weird", "2026-09-18")


class Interpret(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:"); self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE companies(stock_code TEXT, corp_name TEXT);
            INSERT INTO companies VALUES ('000500','가온전선'),('005930','삼성전자'),('000660','SK하이닉스');
            CREATE TABLE transcript_follow(ticker TEXT, entity_id INTEGER, company_name TEXT);
            INSERT INTO transcript_follow VALUES ('NVDA', 1, 'NVIDIA');
            CREATE TABLE entities(id INTEGER, name TEXT, aliases TEXT);
        """)

    def test_gaon_channel_sentence(self):
        out = cs.interpret(self.conn, "가온전선에 대해서, 올해 전고점들을 기반으로 큰 채널을 그려줘.")
        self.assertTrue(out["draw"])
        self.assertEqual((out["code"], out["name"], out["market"]), ("000500", "가온전선", "kr"))
        self.assertEqual((out["kind"], out["window"], out["swing"], out["fit"]), ("channel", "ytd", 10, "two_point"))

    def test_search_sentences_are_not_draw_requests(self):
        self.assertFalse(cs.interpret(self.conn, "채널 상단을 돌파한 종목을 찾아줘")["draw"])
        self.assertFalse(cs.interpret(self.conn, "삼성전자 52주 신고가인지 알려줘")["draw"])
        self.assertFalse(cs.interpret(self.conn, "삼성전자 채널")["draw"])  # 그리기 동사 없음

    def test_trendline_variants_and_unknown_stock(self):
        out = cs.interpret(self.conn, "삼성전자 최근 6개월 저점 연결해서 추세선 그려줘")
        self.assertEqual((out["kind"], out["window"], out["swing"]), ("trendline_low", "6m", 5))
        out = cs.interpret(self.conn, "SK하이닉스 1년 고점 저항선 회귀로 표시해줘")
        self.assertEqual((out["code"], out["kind"], out["window"], out["fit"]), ("000660", "trendline_high", "1y", "regression"))
        out = cs.interpret(self.conn, "없는회사 채널 그려줘")
        self.assertTrue(out["draw"]); self.assertIsNone(out["code"])

    def test_us_ticker(self):
        out = cs.interpret(self.conn, "NVDA 올해 채널 그려줘")
        self.assertEqual((out["code"], out["market"], out["name"]), ("NVDA", "us", "NVIDIA"))


if __name__ == "__main__":
    unittest.main()
