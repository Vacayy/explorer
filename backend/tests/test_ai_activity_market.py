"""'AI가 최근 만든 것' — 시장 정리(Market Today·Overnight)·소스 관점 정리·큰 그림·시장 해설도 담는다 (2026-11-11)."""
import sqlite3
import unittest

from routers import spine_home


class MarketOutputsTests(unittest.TestCase):
    def setUp(self):
        c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
        c.executescript("""
            CREATE TABLE market_today(trade_date TEXT, slot TEXT, created_at TEXT);
            CREATE TABLE us_briefings(trade_date TEXT, created_at TEXT);
            CREATE TABLE source_digests(kind TEXT, key TEXT, created_at TEXT);
            CREATE TABLE era_commentary(created_at TEXT);
            CREATE TABLE telegram_channels(channel_name TEXT, display_name TEXT, is_active INT);
            INSERT INTO market_today VALUES ('2026-11-10','1130',datetime('now','-1 hour')),
                                            ('2026-11-10','1600',datetime('now','-30 minutes')),
                                            ('2026-10-01','0930','2026-10-01 00:30:00');
            INSERT INTO us_briefings VALUES ('2026-11-10', datetime('now'));
            INSERT INTO source_digests VALUES ('telegram','bornlupin',datetime('now')),('big_picture','2026-W46',datetime('now')),
                                              ('person','7',datetime('now'));
            INSERT INTO era_commentary VALUES (datetime('now'));
            INSERT INTO telegram_channels VALUES ('bornlupin','루팡',1);
        """)
        self.out = {x["title"]: x for x in spine_home._market_outputs(c, "-7 days")}

    def test_titles_and_links(self):
        self.assertEqual(self.out["Market Today 11/10 11:30"]["to"], "/home/kr?mtdate=2026-11-10&mtslot=1130")
        self.assertIn("Market Today 11/10 마감 정리", self.out)
        self.assertEqual(self.out["Market Overnight 11/10"]["to"], "/home")
        self.assertEqual(self.out["루팡 관점 정리"]["to"], "/source?kind=telegram&key=bornlupin")
        self.assertEqual(self.out["이번 주 큰 그림 2026-W46"]["to"], "/narrative")
        self.assertEqual(self.out["지금 시장 읽기 AI 해설"]["to"], "/home/macro")

    def test_window_and_kinds(self):
        self.assertNotIn("Market Today 10/1 09:30", self.out)          # 기간 밖
        self.assertEqual(len(self.out), 6)                               # person 프로필은 담지 않는다


if __name__ == "__main__":
    unittest.main()
