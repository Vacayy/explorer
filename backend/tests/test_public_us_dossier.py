from contextlib import closing
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipeline import income_flow, us_data
from routers import spine_us, spine_feed
from security import public_us_dossier as public, public_us_season
from security.access_boundary import PublicAccessBoundary
from tests.test_income_flow import NVIDIA_LOOKUP


class PublicUsDossierTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'snapshot.sqlite'
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript('''
                CREATE TABLE public_us_companies(ticker TEXT,company_name TEXT,sector TEXT,market_cap REAL,fiscal_year_end TEXT);
                INSERT INTO public_us_companies VALUES ('NVDA','NVIDIA','semis',1000,'01-31');
                CREATE TABLE transcripts(id INTEGER,ticker TEXT,fiscal_year INTEGER,fiscal_period TEXT,call_date TEXT);
                INSERT INTO transcripts VALUES (7,'NVDA',2027,'Q2','2026-08-20');
                CREATE TABLE us_prices(stock_code TEXT,trade_date TEXT,open REAL,high REAL,low REAL,close REAL,volume REAL);
                INSERT INTO us_prices VALUES ('NVDA','2026-11-12',10.25,11.50,10.05,11.25,100);
                CREATE TABLE us_fundamentals(ticker TEXT,data_json TEXT,fetched_at TEXT);
                INSERT INTO us_fundamentals VALUES ('NVDA','{"price":11.25,"market_cap":1000}','2020-01-01');
                INSERT INTO us_fundamentals VALUES ('PRIVATE','{"private_note":"Canary"}','2026-11-15');
                CREATE TABLE us_quarterly(ticker TEXT,metric TEXT,q TEXT,value REAL);
                CREATE TABLE us_segments(ticker TEXT,q TEXT,segment_name TEXT,revenue REAL);
                INSERT INTO us_segments VALUES ('NVDA','2026-09','Data center',90000000000);
            ''')
            for metric, values in NVIDIA_LOOKUP.items():
                conn.executemany('INSERT INTO us_quarterly VALUES (?,?,?,?)',[('NVDA',metric,q,v) for q,v in values.items()])
            conn.commit()

    def test_stored_values_fractional_prices_and_financials_without_lazy_fallback(self):
        before=self.path.read_bytes()
        with patch.object(us_data,'get_fundamentals',side_effect=AssertionError('refresh')), \
             patch.object(income_flow,'get_connection',side_effect=AssertionError('private connection')):
            d=public.stored_dossier('nvda',path=self.path)
            self.assertEqual(d.fundamentals_fetched_at,'2020-01-01')
            self.assertEqual(d.fundamentals['price'],11.25)
            self.assertIsNone(d.entity_id)
            self.assertEqual(public.stored_prices('nvda',path=self.path)['items'][0]['low'],10.05)
            flow=public.stored_income('nvda','2026-09',path=self.path)
            expected=income_flow.build_us_income_flow(NVIDIA_LOOKUP,'2026-09')
            self.assertEqual(flow.nodes,expected.nodes)
            self.assertEqual(flow.links,expected.links)
            self.assertEqual(flow.segments[0].name,'Data center')
            self.assertEqual(flow.segments[0].value,90000000000)
            self.assertTrue(public.stored_income_quarters('NVDA',path=self.path).quarters)
            with self.assertRaises(LookupError): public.stored_dossier('PRIVATE',path=self.path)
        self.assertEqual(before,self.path.read_bytes())

    def test_public_http_read_boundary(self):
        app=FastAPI();app.include_router(spine_us.router);app.include_router(spine_feed.router)
        paths=['/api/spine/us/{ticker}','/api/spine/us/{ticker}/income-flow','/api/spine/us/{ticker}/income-flow/quarters','/api/spine/feed/company-prices']
        app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies={('GET',p):'public' for p in paths})
        with TestClient(app,base_url='https://beta.example') as client,patch.object(public_us_season,'DB_PATH',self.path):
            for path in ['/api/spine/us/NVDA','/api/spine/us/NVDA/income-flow?q=2026-09','/api/spine/us/NVDA/income-flow/quarters']:
                r=client.get(path);self.assertEqual(r.status_code,200,r.text)
            r=client.get('/api/spine/feed/company-prices?company=NVDA&market=us')
            self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['items'][0]['close'],11.25)
            self.assertEqual(client.get('/api/spine/feed/company-prices?company=NVDA&market=kr').status_code,404)
            self.assertEqual(client.get('/api/spine/us/PRIVATE').status_code,404)
            self.assertEqual(client.get('/api/spine/us/NVDA/income-flow?mode=invalid').status_code,422)
