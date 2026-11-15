"""Public company chart reads stored bars only, without private data or collection."""
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from models.stock_price import StockPriceResponse
from routers import companies
from security import public_financials as public
from security.access_boundary import PublicAccessBoundary


class PublicCompanyPriceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'prices.sqlite'
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript('''
                CREATE TABLE companies(stock_code, corp_name, private_note);
                INSERT INTO companies VALUES ('111111','Public company','PRIVATE_CANARY'),('222222','Empty company','PRIVATE_CANARY');
                CREATE TABLE stock_prices(stock_code,trade_date,open,high,low,close,volume,market_cap,private_note);
                CREATE TABLE private_notes(body);
                INSERT INTO private_notes VALUES ('PRIVATE_CANARY');
            ''')
            self.dates = [(date(2020,1,1)+timedelta(days=i)).isoformat() for i in range(1502)]
            conn.executemany('INSERT INTO stock_prices VALUES (?,?,?,?,?,?,?,?,?)',
                             [('111111',d,10,12,9,11,100,1000,'PRIVATE_CANARY') for d in self.dates])
            conn.execute('UPDATE stock_prices SET open=NULL,close=NULL WHERE trade_date=?', (self.dates[-1],))
        app = FastAPI(); app.include_router(companies.router)
        app.add_middleware(PublicAccessBoundary, routes=app.router.routes,
                           policies={('GET','/api/companies/{stock_code}/prices'): 'public'})
        self.client = TestClient(app); self.addCleanup(self.client.close)
        original = public.financial_connection
        p = patch.object(public,'financial_connection',side_effect=lambda: original(self.path))
        p.start(); self.addCleanup(p.stop)

    def test_actual_public_route_is_bounded_readonly_and_preserves_nulls(self):
        before = self.path.read_bytes()
        with patch.object(companies,'get_connection',side_effect=AssertionError('private DB')), \
             patch('services.krx_service.fetch_stock_prices',side_effect=AssertionError('collector')):
            r = self.client.get('/api/companies/111111/prices')
        self.assertEqual(r.status_code,200,r.text)
        data = StockPriceResponse.model_validate(r.json())
        self.assertEqual(len(data.items),1500)
        self.assertEqual([x.trade_date for x in data.items],self.dates[2:])
        self.assertIsNone(data.items[-1].close)
        self.assertEqual(data.items[-1].market_cap,1000)
        self.assertNotIn('PRIVATE_CANARY',r.text)
        self.assertEqual(r.headers['cache-control'],'no-store')
        self.assertEqual(before,self.path.read_bytes())
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE private_notes SET body='changed private data'")
            conn.execute("UPDATE stock_prices SET private_note='changed private data'")
            conn.execute("INSERT INTO stock_prices VALUES ('other','2026-01-01',1,2,1,2,4,5,'PRIVATE_CANARY')")
        self.assertEqual(self.client.get('/api/companies/111111/prices').json(),r.json())

    def test_unknown_empty_and_method_boundary(self):
        self.assertEqual(self.client.get('/api/companies/unknown/prices').status_code,404)
        r = self.client.get('/api/companies/222222/prices')
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json(),{'items':[]})
        self.assertEqual(self.client.post('/api/companies/111111/prices').status_code,404)

    def test_sql_rejects_private_columns_and_mutations(self):
        conn = public.financial_connection(); self.addCleanup(conn.close)
        for sql in ('SELECT private_note FROM stock_prices','SELECT private_note FROM companies',
                    'SELECT body FROM private_notes','DELETE FROM stock_prices',
                    'PRAGMA query_only=OFF',"ATTACH DATABASE ':memory:' AS other"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                conn.execute(sql)
