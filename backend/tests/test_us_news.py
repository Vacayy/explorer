"""미국 종목 헤드라인 — Yahoo 종목 RSS 적재, 실패는 숨기지 않는다.

yfinance `.news`가 쓰던 엔드포인트가 404를 내 빈 목록만 돌아왔고(2026-09-30~), fetch_news는 이를
성공처럼 넘겨 브리핑의 '왜' 줄이 조용히 비었다.
"""
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

import requests

from pipeline import us_briefing, us_news
from tests.test_job_status import KeepOpen

RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><description>Bond buyers want 15%.</description><guid>g1</guid>
<link>https://www.fool.com/investing/2026/10/15/nvda/?.tsrc=rss</link>
<pubDate>Fri, 16 Oct 2026 04:06:02 +0000</pubDate><title>Lenders Are Getting Nervous. I'd Still Buy Nvidia.</title></item>
<item><description>Taiwan parks.</description><guid>g2</guid>
<link>https://finance.yahoo.com/a.html?.tsrc=rss</link>
<pubDate>Fri, 16 Oct 2026 03:07:02 +0000</pubDate><title>Taiwan plans $4 bln Texas parks</title></item>
</channel></rss>"""


class UsNewsTests(unittest.TestCase):
    def setUp(self):
        raw = sqlite3.connect(":memory:")
        raw.row_factory = sqlite3.Row
        raw.execute("CREATE TABLE us_ticker_news(ticker TEXT, url TEXT, title TEXT, publisher TEXT, published_at TEXT, "
                    "summary TEXT, fetched_at TEXT, PRIMARY KEY(ticker, url))")
        self.conn = KeepOpen(raw)

    def response(self, status=200, text=RSS):
        r = MagicMock(status_code=status, text=text)
        r.raise_for_status.side_effect = None if status == 200 else requests.HTTPError(f"{status}")
        return r

    def test_rss_items_are_stored_with_iso_dates(self):
        with patch.object(us_news, "get_connection", return_value=self.conn), \
             patch.object(us_news.requests, "get", return_value=self.response()):
            n = us_news.fetch_news("NVDA", force=True)
        self.assertEqual(n, 2)
        rows = {r["title"]: dict(r) for r in self.conn.execute("SELECT * FROM us_ticker_news")}
        first = rows["Lenders Are Getting Nervous. I'd Still Buy Nvidia."]
        self.assertEqual(first["published_at"], "2026-10-16T04:06:02Z")
        self.assertEqual(first["publisher"], "fool.com")
        self.assertEqual(first["summary"], "Bond buyers want 15%.")

    def test_http_failure_raises(self):
        with patch.object(us_news, "get_connection", return_value=self.conn), \
             patch.object(us_news.requests, "get", return_value=self.response(status=404, text="Not Found")):
            with self.assertRaises(requests.HTTPError):
                us_news.fetch_news("NVDA", force=True)

    def test_briefing_reports_tickers_whose_headlines_failed(self):
        movers = [{"ticker": "AAA", "flags": ["x"], "name": "Aaa"}, {"ticker": "BBB", "flags": ["x"], "name": "Bbb"},
                  {"ticker": "CCC", "flags": [], "name": "Ccc"}]

        def fetch(ticker, force=False):
            if ticker == "BBB":
                raise requests.ConnectionError("down")
            return 0
        with patch.object(us_news, "fetch_news", side_effect=fetch):
            failed = us_briefing._attach_headlines(self.conn, movers, fetch=True)
        self.assertEqual(failed, ["BBB"])


if __name__ == "__main__":
    unittest.main()
