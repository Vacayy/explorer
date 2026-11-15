from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import spine_kr
from security.access_boundary import PublicAccessBoundary
from security import public_kr_movers as public


class StoredKrMoversTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'stored.sqlite'
        with sqlite3.connect(self.path) as conn:
            conn.executescript('''CREATE TABLE kr_movers(trade_date TEXT, rank INTEGER, stock_code TEXT,
                name TEXT, market TEXT, close INTEGER, volume INTEGER, value_traded INTEGER,
                change_pct REAL, sector TEXT, market_cap INTEGER, is_new INTEGER, fetched_at TEXT);
                CREATE TABLE raw_documents(secret TEXT);
                INSERT INTO raw_documents VALUES ('private-canary');
                INSERT INTO kr_movers VALUES ('2026-11-13',1,'005930','Example','KOSPI',100,100,10000,
                    9,'Technology',100000,1,'2026-11-13 19:00:00');''')

    def test_read_only_preserves_numeric_results_without_private_connection(self):
        before = self.path.read_bytes()
        with patch('pipeline.kr_movers.get_connection', side_effect=AssertionError('private connection')):
            result = public.stored_movers(path=self.path)
        self.assertEqual(result.trade_date, '2026-11-13')
        self.assertEqual(result.items[0].value_traded, 10000)
        self.assertEqual(result.clusters[0].share_pct, 100)
        self.assertTrue(result.idiosyncratic)
        self.assertEqual(result.briefing, [])
        self.assertEqual(before, self.path.read_bytes())
        conn = public.connection(self.path); self.addCleanup(conn.close)
        with self.assertRaises(sqlite3.DatabaseError): conn.execute('SELECT secret FROM raw_documents')
        with self.assertRaises(sqlite3.DatabaseError): conn.execute('DELETE FROM kr_movers')

    def test_public_route_and_force_boundary(self):
        app = FastAPI(); app.include_router(spine_kr.router)
        app.add_middleware(PublicAccessBoundary, routes=app.router.routes, policies={('GET', '/api/spine/kr/movers'): 'public'})
        with TestClient(app, base_url='https://beta.example') as client, patch.object(public, 'DB_PATH', self.path):
            self.assertEqual(client.get('/api/spine/kr/movers').status_code, 200)
            self.assertEqual(client.get('/api/spine/kr/movers?force=true').status_code, 403)
