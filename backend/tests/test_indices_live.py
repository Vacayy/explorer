"""홈 지수 띠 — 장중엔 정기 수집 봉(index_intraday)을 얹고, 휴장 TTL은 다음 개장을 넘기지 않는다 (2026-11-10)."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

from pipeline import indices


class StripLiveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'i.db'
        self.conn = self.connect()
        self.conn.executescript("""
            CREATE TABLE market_indicators(snapshot_date TEXT, indicator TEXT, value REAL, fetched_at TEXT);
            CREATE TABLE index_intraday(market TEXT, key TEXT, trade_date TEXT, hhmm TEXT, value REAL);
            INSERT INTO market_indicators VALUES ('2026-11-06','index_kospi',5000,'2026-11-09 22:00:00'),
                                                 ('2026-11-09','index_kospi',5100,'2026-11-09 22:00:00');
        """)
        self.conn.commit()
        for p in (patch.object(indices, 'get_connection', side_effect=self.connect),
                  patch.object(indices, 'INDICES', [("kospi", "코스피", "^KS11", "한국", "kr")])):
            p.start(); self.addCleanup(p.stop)

    def connect(self):
        c = sqlite3.connect(self.path); c.row_factory = sqlite3.Row; return c

    def bar(self, value):
        self.conn.execute("INSERT INTO index_intraday VALUES ('kr','kospi','2026-11-10','10:30',?)", (value,)); self.conn.commit()

    def strip(self, now):
        with patch.object(indices, 'datetime', wraps=datetime) as dt:
            dt.now.return_value = now
            return indices.get_indices()["items"][0]

    def test_open_session_uses_newer_intraday_bar_against_yesterdays_close(self):
        self.bar(5202)
        it = self.strip(datetime(2026, 11, 10, 1, 40, tzinfo=timezone.utc))   # 10:40 KST
        self.assertEqual(it["price"], 5202)
        self.assertEqual(it["change_pct"], 2.0)          # 어제 종가 5100 대비
        self.assertEqual(it["as_of"], "2026-11-10")
        self.assertEqual(it["fetched_at"], "2026-11-10 01:30:00")
        self.assertFalse(it["lagging"])

    def test_newer_bar_wins_even_if_snapshot_touched_yesterdays_row_later(self):
        self.conn.execute("UPDATE market_indicators SET fetched_at='2026-11-10 01:50:00' WHERE snapshot_date='2026-11-09'")
        self.conn.commit()
        self.bar(5202)                                                         # 10:30 KST 봉 = 01:30 UTC
        it = self.strip(datetime(2026, 11, 10, 1, 55, tzinfo=timezone.utc))
        self.assertEqual(it["price"], 5202)
        self.assertEqual(it["as_of"], "2026-11-10")

    def test_closed_market_keeps_stored_close(self):
        self.bar(5202)
        it = self.strip(datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc))    # 17:00 KST, 장 마감
        self.assertEqual(it["price"], 5100)

    def test_closed_ttl_stops_at_next_open(self):
        self.assertEqual(indices.minutes_to_next_open(datetime(2026, 11, 9, 23, 30, tzinfo=timezone.utc)), 30)  # 08:30 KST
        self.assertIsNone(indices.minutes_to_next_open(datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)))    # 18:00 KST


if __name__ == '__main__':
    unittest.main()
