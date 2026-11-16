"""Public overview against synthetic market and private canary data."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from models.market_overview import MarketOverview
from pipeline import market_overview as mo
from routers import spine_market_overview
from security.access_boundary import PublicAccessBoundary
from security.public_market import market_connection
from tests.test_market_overview import _db, _daily


class PublicMarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fixture.sqlite'
        source = _db()
        for indicator in ('index_kospi', 'index_kosdaq', 'index_sp500', 'index_nasdaq', 'index_dow'):
            _daily(source, indicator, '2026-11-13', [100, 101, 102])
        source.executescript("""
            CREATE TABLE private_notes(body TEXT);
            INSERT INTO private_notes VALUES ('private-canary');
            INSERT INTO stock_prices VALUES ('fixture', '2026-11-12', 10), ('fixture', '2026-11-13', 11);
            UPDATE market_indicators SET extra_json='private-column-canary';
        """)
        source.commit()
        with sqlite3.connect(self.path) as destination:
            source.backup(destination)
        sqlite3.Connection.close(source)
        mo._breadth_memo = None
        self.app = FastAPI()
        self.app.include_router(spine_market_overview.router)
        self.app.add_middleware(PublicAccessBoundary, routes=self.app.router.routes,
            policies={('GET', '/api/spine/market/{market}/overview'): 'public'})
        self.client = TestClient(self.app, base_url='https://beta.example')
        self.addCleanup(self.client.close)

    def test_actual_public_route_keeps_market_contract_and_no_private_data(self):
        before = self.path.read_bytes()
        with patch.object(spine_market_overview, 'market_connection', side_effect=lambda: market_connection(self.path)), \
                patch.object(spine_market_overview, 'get_connection', side_effect=AssertionError('private connection used')):
            for market in ('kr', 'us'):
                response = self.client.get('/api/spine/market/' + market + '/overview')
                self.assertEqual(response.status_code, 200, response.text)
                data = MarketOverview.model_validate(response.json())
                self.assertEqual(data.market, market)
                self.assertEqual(len(data.indices), 2 if market == 'kr' else 3)
                self.assertEqual(data.indices[0].value, 102)
                self.assertNotIn('canary', response.text)
                self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(self.client.get('/api/spine/market/jp/overview').status_code, 422)
        self.assertEqual(self.path.read_bytes(), before)

    def test_original_home_reads_never_schedule_collection_or_read_signals(self):
        from routers import spine_indices, spine_macro
        from pipeline import indices, macro
        app = FastAPI()
        app.include_router(spine_indices.router)
        app.include_router(spine_macro.router)
        app.add_middleware(PublicAccessBoundary, routes=app.router.routes, policies={
            ('GET', '/api/spine/' + route): 'public'
            for route in ('indices', 'indices/breadth', 'macro')})
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO market_indicators(snapshot_date, indicator, value) VALUES ('2026-11-13', 'macro_usdkrw', 1400)")
        before = self.path.read_bytes()
        connect = lambda: market_connection(self.path)
        fail = AssertionError('public read triggered private/collection work')
        with TestClient(app, base_url='https://beta.example') as client, \
                patch.object(spine_indices, 'market_connection', side_effect=connect), \
                patch('security.public_market.market_connection', side_effect=connect), \
                patch.object(spine_indices, 'is_cached', side_effect=fail), \
                patch.object(spine_indices, 'get_connection', side_effect=fail), \
                patch.object(spine_macro, 'snapshot_macro', side_effect=fail), \
                patch.object(macro, '_read_signal', side_effect=fail):
            values = client.get('/api/spine/indices')
            self.assertEqual(values.status_code, 200, values.text)
            kospi = next(i for i in values.json()['items'] if i['key'] == 'kospi')
            self.assertEqual(kospi['price'], 102)
            self.assertEqual(kospi['as_of'], '2026-11-13')
            breadth = client.get('/api/spine/indices/breadth')
            self.assertEqual(breadth.status_code, 200, breadth.text)
            self.assertEqual(breadth.json()['up'], 1)
            context = client.get('/api/spine/macro')
            self.assertEqual(context.status_code, 200, context.text)
            self.assertEqual(context.json()['items'][0]['value'], 1400)
            self.assertIsNone(context.json()['signal'])
            self.assertNotIn('canary', values.text + breadth.text + context.text)
            for endpoint in ('indices/snapshot', 'macro/snapshot'):
                self.assertEqual(client.post('/api/spine/' + endpoint).status_code, 404)
        self.assertEqual(before, self.path.read_bytes())

    def test_sql_permissions_deny_private_columns_tables_and_mutations(self):
        conn = market_connection(self.path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM stock_prices').fetchone()[0], 2)
        for sql in (
            'SELECT body FROM private_notes',
            'SELECT extra_json FROM market_indicators',
            'SELECT name FROM sqlite_master',
            'UPDATE market_indicators SET value=0',
            'DELETE FROM stock_prices',
            'CREATE TABLE injected(value)',
            "ATTACH DATABASE ':memory:' AS other",
            'PRAGMA query_only=OFF',
            'SELECT load_extension(?)',
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                conn.execute(sql, ('fixture',) if '?' in sql else ())

    def test_missing_file_is_not_created(self):
        missing = self.path.parent / 'missing.sqlite'
        with self.assertRaises(sqlite3.OperationalError): market_connection(missing)
        self.assertFalse(missing.exists())


if __name__ == '__main__':
    unittest.main()
