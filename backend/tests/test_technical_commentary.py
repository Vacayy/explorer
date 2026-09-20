"""기술적 분석 AI 해설 — 근거 검증·재사용·모델 미호출 경로 (D-191)."""
import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from pipeline import technical_commentary as tc
from pipeline.technical_scan import scan_rows


def rows(n=300, start=100.0):
    out, price = [], start
    for i in range(n):
        price = price * (1 + (0.004 if i % 7 else -0.01))
        out.append({"date": f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}", "open": price * 0.99, "high": price * 1.02,
                    "low": price * 0.98, "close": price, "volume": 1000 + i * 3, "shares": None})
    return out


class Commentary(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(tc.SCHEMA + """
            CREATE TABLE stock_prices (stock_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER, shares INTEGER);
        """)
        self.conn.executemany("INSERT INTO stock_prices VALUES ('005930',?,?,?,?,?,?,NULL)",
                              [(r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"]) for r in rows()])
        self.conn.commit()
        self.context = tc.build_context(scan_rows(rows(), within=5), tc.price_context(rows()))

    def test_price_context_is_deterministic_and_complete(self):
        price = tc.price_context(rows())
        self.assertEqual(price["sessions"], 300)
        for key in ("close", "ret_20d", "ret_60d", "ret_120d", "from_52w_high_pct", "from_52w_low_pct", "volume_vs_20d_avg"):
            self.assertIsNotNone(price[key], key)

    def test_finalize_drops_sentences_without_valid_basis(self):
        state = self.context["states"][0]["id"]
        raw = {"summary": "요약", "caveats": ["뉴스는 보지 않음"],
               "reading": [{"text": "근거 있음", "basis": [state, "made_up"]}, {"text": "근거 없음", "basis": ["made_up"]},
                           {"text": "가격 근거", "basis": ["price.ret_20d"]}],
               "watch": [{"text": "빈 근거", "basis": []}]}
        out = tc.finalize(raw, self.context)
        self.assertEqual([p["text"] for p in out["reading"]], ["근거 있음", "가격 근거"])
        self.assertEqual(out["reading"][0]["basis"], [state])
        self.assertEqual(out["watch"], [])
        self.assertEqual(out["dropped_unsupported"], 2)

    def test_finalize_rejects_non_json_and_bad_shape(self):
        with self.assertRaises(tc.CommentaryUnavailable):
            tc.finalize(None, self.context)
        with self.assertRaises(tc.CommentaryUnavailable):
            tc.finalize({"reading": []}, self.context)  # summary 없음

    def test_explain_stores_and_reuses_within_24h(self):
        calls = []

        def runner(context):
            calls.append(context)
            state = context["states"][0]["id"]
            return {"summary": "s", "reading": [{"text": "t", "basis": [state]}], "caveats": [], "watch": []}, 0.01

        first, reused = tc.explain(self.conn, "005930", "kr", 5, runner=runner)
        self.assertFalse(reused)
        self.assertEqual(first["reading"][0]["text"], "t")
        self.assertIn(self.context["states"][0]["id"], first["basis_labels"])
        self.assertEqual(first["as_of"], self.context["as_of"])
        second, reused = tc.explain(self.conn, "005930", "kr", 5, runner=runner)
        self.assertTrue(reused)
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(len(calls), 1)
        # 다른 범위는 별도 해설
        tc.explain(self.conn, "005930", "kr", 20, runner=runner)
        self.assertEqual(len(calls), 2)
        # 강제 재생성
        tc.explain(self.conn, "005930", "kr", 5, force=True, runner=runner)
        self.assertEqual(len(calls), 3)

    def test_explain_refuses_when_no_supported_sentence(self):
        def runner(context):
            return {"summary": "s", "reading": [{"text": "t", "basis": ["nope"]}], "caveats": [], "watch": []}, 0.01
        with self.assertRaises(tc.CommentaryUnavailable):
            tc.explain(self.conn, "005930", "kr", 5, runner=runner)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM technical_commentaries").fetchone()[0], 0)

    def test_stale_commentary_is_regenerated(self):
        def runner(context):
            return {"summary": "s", "reading": [{"text": "t", "basis": [context["states"][0]["id"]]}], "caveats": [], "watch": []}, None
        first, _ = tc.explain(self.conn, "005930", "kr", 5, runner=runner)
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute("UPDATE technical_commentaries SET created_at=? WHERE id=?", (old, first["id"]))
        second, reused = tc.explain(self.conn, "005930", "kr", 5, runner=runner)
        self.assertFalse(reused)
        self.assertNotEqual(second["id"], first["id"])
        self.assertIsNone(second["cost_usd"])


if __name__ == "__main__":
    unittest.main()
