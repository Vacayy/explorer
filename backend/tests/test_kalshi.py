"""Kalshi 예측시장 캐러셀 — 응답 파싱·카테고리 가중 섞기·수집 저장 (2026-11-12)."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import kalshi


def ev(ticker, cat, vol=5000, markets=None):
    return {"event_ticker": ticker, "series_ticker": ticker.split("-")[0], "category": cat, "event_title": f"{ticker}?",
            "event_subtitle": "On Dec 9", "recent_volume": vol, "total_volume": vol * 10,
            "markets": markets if markets is not None else [
                {"yes_subtitle": "A", "last_price_dollars": "0.3000", "previous_price_dollars": "0.2500", "volume": 10, "close_ts": "2026-12-09T19:00:00Z"},
                {"yes_subtitle": "B", "last_price_dollars": "0.6500", "previous_price_dollars": "0.7000", "volume": 20, "close_ts": "2026-12-09T19:00:00Z"},
                {"yes_subtitle": "C", "last_price": 4, "volume": 1, "close_ts": "2026-12-01T00:00:00Z"},
                {"yes_subtitle": "D", "last_price": 1, "volume": 1},
            ]}


class KalshiTests(unittest.TestCase):
    def test_parse_sorts_outcomes_by_probability_and_keeps_top3(self):
        e = kalshi.parse_event(ev("KXFED-26DEC", "Economics"))
        self.assertEqual([o["label"] for o in e["outcomes"]], ["B", "A", "C"])
        self.assertEqual((e["outcomes"][0]["price"], e["outcomes"][0]["prev"]), (65.0, 70.0))
        self.assertEqual(e["close_ts"], "2026-12-01T00:00:00Z")

    def test_ladder_shows_strikes_nearest_50(self):
        ms = [{"yes_subtitle": f"Above {k}", "last_price": p} for k, p in ((1, 99), (2, 97), (3, 80), (4, 55), (5, 30), (6, 5))]
        e = kalshi.parse_event(ev("KXCPI-1", "Economics", markets=ms))
        self.assertEqual([o["label"] for o in e["outcomes"]], ["Above 3", "Above 4", "Above 5"])

    def test_skips_daily_series(self):
        x = ev("KXDIESEL-1", "Economics"); x["product_metadata"] = {"series_frequency": "daily"}
        self.assertIsNone(kalshi.parse_event(x))

    def test_parse_drops_thin_or_settled(self):
        self.assertIsNone(kalshi.parse_event(ev("X-1", "Economics", vol=10)))
        self.assertIsNone(kalshi.parse_event(ev("X-2", "Economics", markets=[{"yes_subtitle": "A", "last_price": 50, "result": "yes"}])))

    def test_pick_weights_finance_economics_and_dedupes(self):
        by = {c: [kalshi.parse_event(ev(f"{c[:3].upper()}-{i}", c)) for i in range(8)] for c, _, _ in kalshi.CATEGORIES}
        by["Politics"].insert(0, kalshi.parse_event(ev("FIN-0", "Politics")))     # 다른 카테고리에 같은 이벤트
        out = kalshi.pick(by)
        cats = [e["category"] for e in out]
        self.assertEqual(cats[:6], kalshi.PATTERN)
        self.assertEqual((cats.count("Financials"), cats.count("Economics"), cats.count("Science and Technology"), cats.count("Politics")), (6, 6, 3, 3))
        self.assertEqual(len({e["event_ticker"] for e in out}), len(out))

    def test_collect_stores_and_latest_reads_one_batch(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "k.db"

        def conn():
            c = sqlite3.connect(path); c.row_factory = sqlite3.Row; return c
        with patch.object(kalshi, "get_connection", side_effect=conn):
            def fetch(cat, n):
                if cat == "Politics":
                    raise ValueError("응답 모양 바뀜")
                return [ev(f"{cat[:3]}-{i}", cat) for i in range(2)]
            r = kalshi.collect(fetch)
            self.assertEqual((r["status"], r["events"]), ("ok", 6))
            self.assertTrue(r["degraded"][0].startswith("Politics"))
            d = kalshi.latest()
            self.assertEqual(len(d["items"]), 6)
            self.assertEqual(d["items"][0]["category_label"], "금융")
            self.assertEqual(d["items"][0]["url"], "https://kalshi.com/markets/fin")
            self.assertIsNone(d["items"][0]["outcomes"][0]["change"])          # 기준 수집분 없음
            c = conn()
            c.execute("UPDATE kalshi_events SET fetched_at=datetime(fetched_at, '-1 day')"); c.commit(); c.close()
            kalshi.collect(lambda cat, n: [] if cat == "Politics" else [ev(f"{cat[:3]}-{i}", cat, markets=[
                {"yes_subtitle": "B", "last_price": 72}, {"yes_subtitle": "A", "last_price": 28}]) for i in range(2)])
            d = kalshi.latest()
            self.assertEqual(d["items"][0]["outcomes"][0]["change"], 7.0)      # B 65 → 72
            self.assertEqual(kalshi.collect(lambda c, n: [])["status"], "error")


if __name__ == "__main__":
    unittest.main()
