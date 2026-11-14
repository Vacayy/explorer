"""Real public ETF HTTP projection with private canaries and readonly SQL."""
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from models.industry import UsIndustryMapResponse, UsSectorMarketResponse
from pipeline import us_sectors
from routers import spine_industry
from security.access_boundary import PublicAccessBoundary
from security.public_industry import industry_connection


class PublicIndustryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fixture.sqlite'
        with sqlite3.connect(self.path) as conn:
            conn.executescript('''CREATE TABLE sector_benchmark_prices(ticker, trade_date, close, private_note);
                CREATE TABLE transcript_follow(ticker, active);
                INSERT INTO transcript_follow VALUES ('private-canary', 1);''')
            conn.executemany('INSERT INTO sector_benchmark_prices VALUES (?,?,?,?)',
                [(t, (date(2026, 6, 1) + timedelta(days=i)).isoformat(), 100 + i * slope, 'column-canary')
                 for t, slope in [('SPY', .1), ('XLK', 1), ('SMH', 2)] for i in range(140)])
        app = FastAPI()
        app.include_router(spine_industry.router)
        app.add_middleware(PublicAccessBoundary, routes=app.router.routes,
            policies={('GET', '/api/spine/industry/us/map'): 'public',
                      ('GET', '/api/spine/industry/us/{ticker}/market'): 'public'})
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_public_http_never_reads_follows_or_private_connection(self):
        before = self.path.read_bytes()
        with patch('security.public_industry.industry_connection', side_effect=lambda: industry_connection(self.path)), \
             patch('database.get_connection', side_effect=AssertionError('private connection')), \
             patch.object(us_sectors, 'follows', side_effect=AssertionError('personal follows read')):
            response = self.client.get('/api/spine/industry/us/map?include_coverage=true', headers={'x-user-id': 'operator'})
            self.assertEqual(response.status_code, 200, response.text)
            data = UsIndustryMapResponse.model_validate(response.json())
            self.assertEqual(len(data.sectors), 2)
            self.assertEqual(len(data.spy), 61)
            self.assertTrue(all(r.coverage is None and r.ret_3m is not None for r in data.sectors))
            self.assertNotIn('canary', response.text)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            for path in ('/api/spine/industry/map', '/api/spine/industry/us/XLK'):
                self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.path.read_bytes(), before)

    def test_private_map_preserves_coverage(self):
        conn = sqlite3.connect(self.path)
        self.addCleanup(conn.close)
        with patch.object(us_sectors, 'follows', return_value=[{'gics': 'XLK', 'sub': 'SMH'}]) as follows:
            data = us_sectors.us_map(conn)
        follows.assert_called_once()
        self.assertTrue(all(r['coverage'] == 1 for r in data['sectors']))

    def test_empty_and_partial_are_not_personal_fallbacks(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM sector_benchmark_prices WHERE ticker != 'SPY'")
        conn = industry_connection(self.path)
        self.addCleanup(conn.close)
        data = us_sectors.us_map(conn, include_coverage=False)
        self.assertEqual(data['sectors'], [])
        self.assertEqual(len(data['spy']), 61)
        with sqlite3.connect(self.path) as writer:
            writer.execute('DELETE FROM sector_benchmark_prices')
        self.assertEqual(us_sectors.us_map(conn, include_coverage=False), {'as_of': None, 'spy': [], 'sectors': []})

    def test_sql_rejects_personal_columns_tables_and_writes(self):
        conn = industry_connection(self.path)
        self.addCleanup(conn.close)
        for sql in ('SELECT * FROM transcript_follow', 'SELECT private_note FROM sector_benchmark_prices',
                    'SELECT name FROM sqlite_master', 'DELETE FROM sector_benchmark_prices',
                    'PRAGMA query_only=OFF', "ATTACH DATABASE ':memory:' AS other"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                conn.execute(sql)
        missing = self.path.parent / 'missing.sqlite'
        with self.assertRaises(sqlite3.OperationalError): industry_connection(missing)
        self.assertFalse(missing.exists())

    def test_public_detail_reads_only_etf_prices_and_omits_personal_fields(self):
        before = self.path.read_bytes()
        with patch('security.public_industry.industry_connection', side_effect=lambda: industry_connection(self.path)), \
             patch.object(us_sectors, 'us_sector_detail', side_effect=AssertionError('private detail called')), \
             patch.object(us_sectors, 'follows', side_effect=AssertionError('private follows read')), \
             patch.object(us_sectors, '_docs', side_effect=AssertionError('private docs read')), \
             patch.object(us_sectors, 'data_links', side_effect=AssertionError('private derived links read')):
            response = self.client.get('/api/spine/industry/us/smh/market?tab=stocks')
            self.assertEqual(response.status_code, 200, response.text)
            data = UsSectorMarketResponse.model_validate(response.json())
            self.assertEqual(data.ticker, 'SMH')
            self.assertEqual(data.parent, 'XLK')
            self.assertEqual(len(data.series), 140)
            self.assertEqual(data.series[-1].v, 378)
            self.assertIsNotNone(data.series[-1].k)
            self.assertEqual(data.siblings[0].ticker, 'XLK')
            self.assertTrue({'coverage', 'members', 'docs', 'data_links'}.isdisjoint(response.json()))
            self.assertNotIn('canary', response.text)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(self.client.get('/api/spine/industry/us/NOPE/market').status_code, 404)
            self.assertEqual(self.client.get('/api/spine/industry/us/SMH').status_code, 404)
        self.assertEqual(self.path.read_bytes(), before)

    def test_public_detail_empty_and_partial_keep_ticker_without_private_fallback(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM sector_benchmark_prices WHERE ticker = 'SPY'")
        conn = industry_connection(self.path)
        self.addCleanup(conn.close)
        partial = UsSectorMarketResponse.model_validate(us_sectors.us_sector_market(conn, 'SMH'))
        self.assertIsNone(partial.as_of)
        self.assertTrue(partial.series)
        self.assertTrue(all(point.k is None for point in partial.series))
        empty = UsSectorMarketResponse.model_validate(us_sectors.us_sector_market(conn, 'XLV'))
        self.assertEqual(empty.series, [])
        self.assertIsNone(empty.last)
