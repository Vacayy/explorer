from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipeline import trend_leaders as trend
from security import public_trend as public
from security.access_boundary import PublicAccessBoundary
from routers import spine_trend


class PublicTrendTests(unittest.TestCase):
    def test_stored_calculations_chart_and_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'snapshot.sqlite'
            with closing(sqlite3.connect(path)) as conn:
                conn.row_factory=sqlite3.Row
                conn.executescript('''CREATE TABLE stock_prices(stock_code TEXT,trade_date TEXT,high REAL,low REAL,
                    close REAL,volume REAL,market_cap REAL,fetched_at TEXT);
                    CREATE TABLE companies(stock_code TEXT,corp_name TEXT);
                    CREATE TABLE public_kr_company_sectors(stock_code TEXT,sector TEXT);
                    CREATE TABLE portfolio(secret TEXT);
                    INSERT INTO companies VALUES ('000001','Example');
                    INSERT INTO public_kr_company_sectors VALUES ('000001','Technology');''')
                for i in range(340):
                    price=100 if i<260 else 100*1.006**(i-259)
                    conn.execute('INSERT INTO stock_prices VALUES (?,?,?,?,?,?,?,?)',('000001',f'd{i:04d}',price*1.01,price*.99,price,1000,1e12,'stamp'))
                conn.commit()
                expected=trend.read_compute(conn,sectors={'000001':'Technology'})
                expected_chart=trend.read_chart(conn,'000001')
            before=path.read_bytes()
            with patch.object(trend,'get_connection',side_effect=AssertionError('private connection')), patch.dict(trend._cache,{('d0339','stamp'):{'private':'canary'}},clear=True):
                actual=public.stored_trends(path=path)
                self.assertEqual(actual,expected);self.assertEqual(len(actual['items']),1)
                self.assertEqual(public.stored_chart('000001',path=path),expected_chart)
            self.assertEqual(before,path.read_bytes())
            with patch.object(public, 'read_compute', side_effect=AssertionError('recomputed unchanged snapshot')):
                self.assertEqual(public.stored_trends(path=path), expected)
            replacement=Path(tmp)/'replacement.sqlite'
            replacement.write_bytes(path.read_bytes())
            with closing(sqlite3.connect(replacement)) as conn:
                conn.execute("UPDATE companies SET corp_name='Updated'")
                conn.commit()
            replacement.replace(path)
            self.assertEqual(public.stored_trends(path=path)['items'][0]['name'], 'Updated')
            with closing(public.connection(path)) as conn:
                with self.assertRaises(sqlite3.DatabaseError):conn.execute('SELECT secret FROM portfolio')
                with self.assertRaises(sqlite3.DatabaseError):conn.execute('DELETE FROM stock_prices')
            app=FastAPI();app.include_router(spine_trend.router)
            app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies={
                ('GET','/api/spine/trend-leaders'):'public',('GET','/api/spine/trend-leaders/{code}/chart'):'public'})
            with TestClient(app,base_url='https://beta.example') as client,patch.object(public,'DB_PATH',path):
                self.assertEqual(client.get('/api/spine/trend-leaders').status_code,200)
                self.assertEqual(client.get('/api/spine/trend-leaders/000001/chart').status_code,200)
                self.assertEqual(client.get('/api/spine/trend-leaders/invalid/chart').status_code,422)
