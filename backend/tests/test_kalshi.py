"""Kalshi 예측시장 캐러셀 — 응답 파싱·카테고리 가중 섞기·수집 저장 (2026-11-12)."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
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
            r = kalshi.collect(fetch, candles=lambda *a: [])
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
                {"yes_subtitle": "B", "last_price": 72}, {"yes_subtitle": "A", "last_price": 28}]) for i in range(2)], candles=lambda *a: [])
            d = kalshi.latest()
            self.assertEqual(d["items"][0]["outcomes"][0]["change"], 7.0)      # B 65 → 72
            self.assertEqual(kalshi.collect(lambda c, n: [], candles=lambda *a: [])["status"], "error")


V2_EVENT = {"event_ticker": "KXPIN-1", "series_ticker": "KXPIN", "category": "Politics", "title": "Pinned?", "sub_title": "By 2027",
            "mutually_exclusive": True,
            "markets": [{"ticker": "KXPIN-1-A", "yes_sub_title": "A", "last_price_dollars": "0.6200", "volume_24h_fp": "10.5",
                         "volume_fp": "900", "close_time": "2027-01-01T00:00:00Z", "status": "active", "result": "",
                         "rules_primary": "If A, resolves Yes."},
                        {"ticker": "KXPIN-1-B", "yes_sub_title": "B", "last_price_dollars": "0.3800", "volume_24h_fp": "2",
                         "volume_fp": "100", "close_time": "2027-01-01T00:00:00Z", "status": "active", "result": ""}]}


class KalshiPinDetailTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "k.db"
        c = self.conn(); c.execute("CREATE TABLE cache_meta (cache_key TEXT PRIMARY KEY, fetched_at TEXT, expires_at TEXT)"); c.commit(); c.close()
        for p in (patch.object(kalshi, "get_connection", side_effect=self.conn),
                  patch("services.cache_service.get_connection", side_effect=self.conn)):
            p.start(); self.addCleanup(p.stop)

    def conn(self):
        c = sqlite3.connect(self.path); c.row_factory = sqlite3.Row; return c

    def test_pinned_event_kept_first_even_when_not_trending_and_spark_stored(self):
        kalshi.set_pin("KXPIN-1", "KXPIN", True)
        calls = []
        r = kalshi.collect(lambda cat, n: [ev("FIN-0", "Financials", markets=[{"ticker": "FIN-0-X", "yes_subtitle": "X", "last_price": 40}])] if cat == "Financials" else [],
                           event=lambda t: V2_EVENT, candles=lambda s, m, d: calls.append(m) or [("2026-11-10", 50.0), ("2026-11-11", 55.0)])
        self.assertEqual((r["status"], r["events"], r["pinned"]), ("ok", 2, 1))
        d = kalshi.latest()
        self.assertEqual([(e["event_ticker"], e["pinned"]) for e in d["items"]], [("KXPIN-1", True), ("FIN-0", False)])
        self.assertEqual(d["items"][0]["spark"], [["2026-11-10", 50.0], ["2026-11-11", 55.0]])
        self.assertEqual(sorted(calls), ["FIN-0-X", "KXPIN-1-A"])
        kalshi.set_pin("KXPIN-1", "KXPIN", False)
        self.assertFalse(kalshi.latest()["items"][0]["pinned"])

    def test_detail_uses_cache_within_ttl(self):
        n = {"event": 0, "candles": 0}
        def event(t):
            n["event"] += 1; return V2_EVENT
        def candles(s, m, d):
            n["candles"] += 1; return [(datetime.now(timezone.utc).date().isoformat(), 60.0)]   # 범위 필터가 실제 날짜 기준
        d = kalshi.detail("KXPIN-1", "1m", event=event, candles=candles)
        kalshi.detail("KXPIN-1", "1m", event=event, candles=candles)
        self.assertEqual(n, {"event": 1, "candles": 2})
        self.assertEqual([o["label"] for o in d["outcomes"]], ["A", "B"])
        self.assertEqual(d["rules"], "If A, resolves Yes.")
        self.assertEqual([s["label"] for s in d["series"]], ["A", "B"])
        self.assertEqual(len(d["series"][0]["points"]), 1)

    def test_ladder_outcomes_sorted_by_strike(self):
        self.assertEqual(sorted([{"label": "Above 3.4%"}, {"label": "Above 3.0%"}, {"label": "Above 10,000"}], key=kalshi._strike),
                         [{"label": "Above 3.0%"}, {"label": "Above 3.4%"}, {"label": "Above 10,000"}])


if __name__ == "__main__":
    unittest.main()
