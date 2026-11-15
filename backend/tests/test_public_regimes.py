from contextlib import closing
from datetime import date,timedelta
from pathlib import Path
import sqlite3,tempfile,unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from security import public_regimes,public_us_season
from security.access_boundary import PublicAccessBoundary
from routers import spine_regimes
from pipeline import regimes
from models.regimes import RegimesResponse,BrkResponse

class PublicRegimesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'snapshot.sqlite'
        with closing(sqlite3.connect(self.path)) as c,c:
            c.executescript('CREATE TABLE us_prices(stock_code,trade_date,close);CREATE TABLE public_regime_recessions(snapshot_date,value);CREATE TABLE private_checks(note);INSERT INTO private_checks VALUES("private canary");')
            for ticker in regimes.TICKERS:
                factor=2 if ticker=='BRK-A' else 1
                c.executemany('INSERT INTO us_prices VALUES(?,?,?)',[(ticker,(date(2000,1,1)+timedelta(days=i)).isoformat(),factor*(100+i*.1 if i<500 else 200-(i-500)*.1)) for i in range(1000)])
            c.executemany('INSERT INTO public_regime_recessions VALUES(?,?)',[('2001-01-01',1),('2001-02-01',1),('2001-03-01',0)])

    def test_readonly_models_and_all_comparison_options(self):
        before=self.path.read_bytes()
        with patch.object(regimes,'get_connection',side_effect=AssertionError('private DB')),patch.object(regimes,'collect',side_effect=AssertionError('collector')):
            r=RegimesResponse.model_validate(public_regimes.stored_regimes(path=self.path))
            self.assertTrue(r.phases);self.assertEqual(r.recessions[0].end,'2001-02-28')
            for bench in regimes.BENCHES:
                for span in regimes.RANGES:
                    b=BrkResponse.model_validate(public_regimes.stored_brk(bench,span,path=self.path))
                    self.assertTrue(b.points)
        self.assertEqual(self.path.read_bytes(),before)
        with closing(public_us_season.connection(self.path)) as c:
            with self.assertRaises(sqlite3.DatabaseError):c.execute('select note from private_checks')
            with self.assertRaises(sqlite3.DatabaseError):c.execute('delete from us_prices')

    def test_rejects_bad_observations(self):
        with closing(sqlite3.connect(self.path)) as c,c:c.execute('UPDATE public_regime_recessions SET value=2')
        with self.assertRaises(ValueError):public_regimes.stored_regimes(path=self.path)
        with closing(sqlite3.connect(self.path)) as c,c:
            c.execute('UPDATE public_regime_recessions SET value=0');c.execute('UPDATE us_prices SET close=0')
        with self.assertRaises(ValueError):public_regimes.stored_regimes(path=self.path)

    def test_public_routes_without_collection_checks_or_commentary(self):
        app=FastAPI();app.include_router(spine_regimes.router)
        app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies={('GET','/api/spine/regimes'):'public',('GET','/api/spine/regimes/brk'):'public'})
        with TestClient(app) as client,patch.object(public_us_season,'DB_PATH',self.path),patch.object(spine_regimes,'get_regimes',side_effect=AssertionError('private read')):
            self.assertEqual(client.get('/api/spine/regimes').status_code,200)
            self.assertEqual(client.get('/api/spine/regimes/brk?bench=nasdaq&range=5y').status_code,200)
            self.assertEqual(client.get('/api/spine/regimes/brk?bench=SECRET').status_code,422)
            for method,url in [('post','/api/spine/regimes/collect'),('get','/api/spine/regimes/state'),('get','/api/spine/regimes/commentary'),('put','/api/spine/regimes/checks/secret')]:
                self.assertEqual(getattr(client,method)(url).status_code,404)
