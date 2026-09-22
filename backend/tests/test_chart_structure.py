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


class Draw(unittest.TestCase):
    def test_null_bars_are_excluded_from_candles_and_noted(self):
        conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
        conn.executescript("CREATE TABLE us_prices (stock_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, fetched_at TEXT);")
        for r in rows(n=150):
            conn.execute("INSERT INTO us_prices VALUES ('INTC',?,?,?,?,?,?,NULL)", (r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"]))
        conn.execute("INSERT INTO us_prices VALUES ('INTC','2026-09-21',NULL,NULL,NULL,NULL,NULL,NULL)")  # yfinance NaN 봉
        out = cs.draw(conn, "INTC", "us", "channel", "2026-01-01:2026-12-31", 5, "two_point")
        self.assertTrue(all(isinstance(c["close"], float) for c in out["candles"]))
        self.assertNotIn("2026-09-21", [c["time"] for c in out["candles"]])
        self.assertTrue(any("비어 있는 봉 1개" in n for n in out["notes"]))


class Levels(unittest.TestCase):
    def test_levels_cluster_touches_and_split_by_role(self):
        r = rows(n=120, slope=0.0)  # 수평 박스: 고점 106, 저점 94가 반복
        out = cs.structure(r, "levels", 5)
        self.assertEqual(out["kind"], "levels")
        prices = sorted(round(l["price"]) for l in out["summary"]["levels"])
        self.assertIn(106, prices); self.assertIn(94, prices)
        top = max(out["summary"]["levels"], key=lambda l: l["touches"])
        self.assertGreaterEqual(top["touches"], 4)
        roles = {round(l["price"]): l["role"] for l in out["summary"]["levels"]}
        self.assertEqual(roles[106], "resistance"); self.assertEqual(roles[94], "support")
        self.assertEqual(out["summary"]["nearest_resistance"], next(l["price"] for l in out["summary"]["levels"] if round(l["price"]) == 106))
        self.assertTrue(all(len(l["points"]) == 2 and l["points"][0]["value"] == l["points"][1]["value"] for l in out["lines"]))

    def test_conditions_are_valid_catalog_conditions(self):
        for kind in cs.KINDS:
            for fit in cs.FITS:
                for item in cs.to_conditions(kind, 10, fit, 171):
                    self.assertEqual(item["params"]["pivot_width"], 10)
                    self.assertEqual(item["params"]["lookback"], 171)
                    self.assertIn("phrase", item)
        self.assertEqual(cs.to_conditions("channel", 40, "two_point", 5)[0]["params"]["pivot_width"], 30)
        self.assertEqual(cs.to_conditions("channel", 2, "two_point", 5)[0]["params"]["lookback"], 20)


class InterpretP1(unittest.TestCase):
    def setUp(self):
        Interpret.setUp(self)

    def test_multiple_stocks_and_levels(self):
        out = cs.interpret(self.conn, "삼성전자와 SK하이닉스 1년 지지·저항 레벨 그려서 비교해줘", assist=None)
        self.assertEqual(out["codes"], ["005930", "000660"])
        self.assertEqual(out["kind"], "levels")
        self.assertIn("종목 2개 비교", out["matched"])

    def test_model_assist_only_when_rules_fail(self):
        calls = []
        def assist(text): calls.append(text); return ["가온 전선"]
        out = cs.interpret(self.conn, "그 전선회사 올해 채널 그려줘", assist=assist)
        self.assertEqual(out["code"], "000500"); self.assertEqual(len(calls), 1)
        self.assertTrue(any("모델 보조" in m for m in out["matched"]))
        out = cs.interpret(self.conn, "가온전선 올해 채널 그려줘", assist=assist)
        self.assertEqual(len(calls), 1)  # 규칙이 찾으면 모델을 부르지 않음
        def broken(text): raise RuntimeError("cli down")
        out = cs.interpret(self.conn, "그 전선회사 올해 채널 그려줘", assist=broken)
        self.assertIsNone(out["code"]); self.assertIn("모델 보조 실패", out["matched"])
