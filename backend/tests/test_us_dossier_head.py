"""미국 도시에 머리 첫 줄 — 업종·비교 ETF는 실적 시즌 섹터 표와 같은 판정, 팔로우 밖이면 비운다(D-306 2)."""
import sqlite3
import unittest

from routers.spine_us import _sector


class UsDossierSectorTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE transcript_follow(ticker TEXT, group_label TEXT, sic TEXT, active INT);
            INSERT INTO transcript_follow VALUES ('NVDA', 'M7', '3674', 1), ('VRT', 'dc-infra', '3600', 1), ('OLD', 'software', '7372', 0);
        """)

    def test_ticker_and_group_sectors(self):
        self.assertEqual(_sector(self.conn, "NVDA"), ("반도체", "SMH"))
        self.assertEqual(_sector(self.conn, "VRT"), ("데이터센터 설비", "XLI"))

    def test_unfollowed_is_empty(self):
        self.assertEqual(_sector(self.conn, "OLD"), (None, None))
        self.assertEqual(_sector(self.conn, "ZZZZ"), (None, None))


if __name__ == "__main__":
    unittest.main()
