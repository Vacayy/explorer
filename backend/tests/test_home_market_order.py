import sqlite3
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pipeline import indices, kr_movers


class MarketHomeTests(unittest.TestCase):
    def test_taiwan_session_and_symbol(self):
        self.assertIn(('twii', '대만증시', '^TWII', '대만', 'tw'), indices.INDICES)
        self.assertTrue(indices.market_status('tw', datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc))['is_open'])
        self.assertFalse(indices.market_status('tw', datetime(2026, 9, 10, 5, 30, tzinfo=timezone.utc))['is_open'])
        self.assertEqual(indices.market_status('tw')['hours_kst'], '10:00–14:30')

    def test_briefing_filters_dates_entities_and_duplicate_enrichments(self):
        c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
        c.executescript('''
        CREATE TABLE raw_documents(id INTEGER, title TEXT, source_type TEXT, published_at TEXT, markdown TEXT, raw_content TEXT);
        CREATE TABLE enrichments(id INTEGER, doc_id INTEGER, summary TEXT);
        CREATE TABLE entities(id INTEGER, type TEXT, name TEXT, aliases TEXT);
        CREATE TABLE entity_links(doc_id INTEGER, entity_id INTEGER);
        INSERT INTO entities VALUES(1,'company','회사A','005930'),(2,'company','회사B','000660');
        INSERT INTO raw_documents VALUES
          (1,'당일','blog','2026-09-07T14:59:00Z',NULL,NULL),
          (2,'익일 KST','blog','2026-09-07T15:00:00Z',NULL,NULL),
          (3,'너무 오래됨','blog','2026-09-01T00:00:00Z',NULL,NULL),
          (4,'다른 회사','blog','2026-09-07T00:00:00Z',NULL,NULL);
        INSERT INTO entity_links VALUES(1,1),(1,1),(2,1),(3,1),(4,2);
        INSERT INTO enrichments VALUES(1,1,'구 요약'),(2,1,'회사A 최근 요약');
        ''')
        with patch.object(kr_movers,'get_connection',return_value=c):
            data=kr_movers._briefing_evidence([{'trade_date':'2026-09-07','stock_code':'005935','name':'회사A우','rank':1}])
        self.assertTrue(data[0]['parent_company_context'])
        self.assertEqual(len(data[0]['documents']),1)
        self.assertEqual(data[0]['documents'][0]['excerpt'],'회사A 최근 요약')
        self.assertEqual(data[0]['documents'][0]['doc_id'],1)

    def test_empty_briefing_does_not_open_db(self):
        with patch.object(kr_movers,'get_connection') as connect:
            self.assertEqual(kr_movers._briefing_evidence([]),[])
            connect.assert_not_called()
