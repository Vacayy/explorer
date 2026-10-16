"""컨콜 프록시 추출은 '못 찾음'도 기록해 같은 쌍을 매일 다시 부르지 않는다.

found=false를 남기지 않아 (프록시, 컨콜) 앞쪽 쌍을 매일 haiku로 다시 판정했고, 회당 상한(40)에 막혀
뒤쪽 컨콜로 넘어가지 못했다(2026-10-16 재가동 전 발견).
"""
import sqlite3
import unittest
from unittest.mock import patch

from pipeline import enrich, transcript
from tests.test_job_status import KeepOpen


class ProxyScanTests(unittest.TestCase):
    def setUp(self):
        raw = sqlite3.connect(":memory:")
        raw.row_factory = sqlite3.Row
        raw.executescript("""
            CREATE TABLE proxy_registry(id INTEGER PRIMARY KEY, key TEXT, label TEXT, tickers TEXT, unit TEXT, extract_hint TEXT, active INT);
            CREATE TABLE transcripts(id INTEGER PRIMARY KEY, ticker TEXT, call_date TEXT, fiscal_year INT, raw_doc_id INT);
            CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, markdown TEXT);
            CREATE TABLE proxy_observations(id INTEGER PRIMARY KEY, proxy_id INT, transcript_id INT, source_type TEXT, source_id TEXT,
                observed_at TEXT, value_num REAL, value_text TEXT, direction TEXT);
            CREATE TABLE proxy_scans(proxy_id INT, transcript_id INT, scanned_at TEXT DEFAULT (datetime('now')), PRIMARY KEY(proxy_id, transcript_id));
            INSERT INTO proxy_registry VALUES (1, 'capex', 'CAPEX', 'MSFT,GOOGL', '$B', '', 1), (2, 'ai', 'AI 매출', 'MSFT', '%', '', 1);
            INSERT INTO raw_documents VALUES (1, 'call a'), (2, 'call b'), (3, 'call c');
            INSERT INTO transcripts VALUES (1, 'MSFT', '2026-07-01', 2026, 1), (2, 'GOOGL', '2026-07-02', 2026, 2), (3, 'MSFT', '2026-04-01', 2025, 3);
        """)
        self.conn = KeepOpen(raw)

    def extract(self, limit, answer='{"found": false}'):
        with patch.object(transcript, "get_connection", return_value=self.conn), \
             patch.object(transcript, "project_numeric_observations"), \
             patch.object(enrich, "llm_available", return_value=True), \
             patch.object(enrich, "_call_claude_code", return_value=answer) as call:
            r = transcript.extract_proxies(limit=limit)
        return r, call.call_count

    def test_not_found_pairs_are_not_rescanned_and_scanning_advances(self):
        _, first = self.extract(limit=2)
        _, second = self.extract(limit=2)
        _, third = self.extract(limit=2)
        # 프록시마다 최근 컨콜 limit개가 대상. 1회: CAPEX 2쌍 → 2회: 다음 프록시(AI 매출) 2쌍 → 3회: 0
        # 고치기 전엔 1회의 2쌍을 매번 다시 불러 (2, 2, 2)였다
        self.assertEqual((first, second, third), (2, 2, 0))

    def test_found_pairs_are_observations(self):
        r, n = self.extract(limit=5, answer='{"found": true, "value_num": 80, "direction": "up"}')
        self.assertEqual((r["extracted"], n), (5, 5))   # CAPEX 3쌍 + AI 매출 2쌍
        self.assertEqual(self.extract(limit=5)[1], 0)


if __name__ == "__main__":
    unittest.main()
