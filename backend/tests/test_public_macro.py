from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import spine_macro
from security import public_macro as public
from security.access_boundary import PublicAccessBoundary
from pipeline import macro


class PublicMacroTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'macro.sqlite'
        with closing(sqlite3.connect(self.path)) as c, c:
            c.executescript('CREATE TABLE market_indicators(indicator,snapshot_date,value,private_note); CREATE TABLE macro_signals(comment); CREATE TABLE era_checks(note); CREATE TABLE meta(key,value); CREATE TABLE source_receipts(key,receipt_json);')
            c.execute("INSERT INTO meta VALUES ('schema','public_macro_direct_v1')")
            for key,(_,sid,_,url) in public.SOURCES.items():
                c.execute('INSERT INTO source_receipts VALUES (?,?)',(key,json.dumps({'series_id':sid,'source_url':url,'sha256':'a'*64})))
            for key in ('risk_us2y','risk_us10y','macro_usdkrw','private_canary'):
                c.executemany('INSERT INTO market_indicators VALUES (?,?,?,?)',[(key,f'2026-10-{i:02d}',i,'SECRET') for i in range(1,8)])
            c.execute("INSERT INTO macro_signals VALUES ('SECRET')")
        app=FastAPI();app.include_router(spine_macro.router)
        app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies={('GET','/api/spine/macro/public'):'public'})
        self.client=TestClient(app);self.addCleanup(self.client.close)
        original=public.macro_connection
        self.original_connection=original
        p=patch.object(public,'macro_connection',side_effect=lambda:original(self.path));p.start();self.addCleanup(p.stop)

    def test_public_reads_only_reviewed_inputs_without_lazy_collection(self):
        before=self.path.read_bytes()
        with patch.object(spine_macro,'snapshot_macro',side_effect=AssertionError('collector')), patch.object(macro,'get_connection',side_effect=AssertionError('hidden DB')), patch.object(macro,'_read_signal',side_effect=AssertionError('private signal')):
            r=self.client.get('/api/spine/macro/public')
        self.assertEqual(r.status_code,200,r.text)
        data=r.json();self.assertEqual({i['key'] for i in data['items']},{'us2y','us10y'})
        self.assertEqual(data['items'][0]['comparison_date'],'2026-10-02')
        self.assertEqual(data['items'][0]['change_pct'],250)
        self.assertEqual(data['items'][0]['sources'][0]['series_id'],'RIFLGFCY02_N.B')
        self.assertEqual(next(x for x in data['coverage'] if x['key']=='usdkrw')['status'],'source_review_pending')
        self.assertNotIn('SECRET',r.text);self.assertNotIn('fred_enabled',data);self.assertNotIn('signal',data)
        self.assertEqual(r.headers['cache-control'],'no-store');self.assertEqual(before,self.path.read_bytes())
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute("UPDATE macro_signals SET comment='CHANGED'")
            c.execute("UPDATE market_indicators SET value=999 WHERE indicator='private_canary'")
        self.assertEqual(self.client.get('/api/spine/macro/public').json(),data)
        self.assertEqual(self.client.get('/api/spine/macro').status_code,404)
        self.assertEqual(self.client.post('/api/spine/macro/snapshot').status_code,404)

    def test_empty_and_invalid_are_not_successful_neutral_signals(self):
        with closing(sqlite3.connect(self.path)) as c, c:c.execute('DELETE FROM market_indicators')
        with patch.object(spine_macro,'snapshot_macro',side_effect=AssertionError('collector')):
            data=self.client.get('/api/spine/macro/public').json()
        self.assertEqual(data['items'],[]);self.assertIsNone(data['as_of'])
        self.assertEqual(data['coverage'][0]['status'],'missing')
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute("INSERT INTO market_indicators VALUES ('risk_us2y','2026-10-01',NULL,'secret')")
        data=self.client.get('/api/spine/macro/public').json()
        self.assertEqual(data['coverage'][0]['status'],'invalid');self.assertEqual(data['items'],[])

    def test_authorizer_denies_private_columns_tables_and_writes(self):
        c=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True);self.addCleanup(c.close)
        c.execute('PRAGMA query_only=ON');c.set_authorizer(public._authorize)
        for sql in ('SELECT comment FROM macro_signals','SELECT note FROM era_checks','SELECT private_note FROM market_indicators','DELETE FROM market_indicators','PRAGMA query_only=OFF'):
            with self.subTest(sql=sql),self.assertRaises(sqlite3.DatabaseError):c.execute(sql)

    def test_direct_snapshot_required_and_receipt_mismatch_excluded(self):
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(Exception):
                self.original_connection()
        with closing(sqlite3.connect(self.path)) as c,c:
            c.execute("UPDATE source_receipts SET receipt_json='{}' WHERE key='us2y'")
        data=self.client.get('/api/spine/macro/public').json()
        self.assertEqual(next(x for x in data['coverage'] if x['key']=='us2y')['status'],'invalid')
        self.assertEqual({x['key'] for x in data['items']},{'us10y'})

    def test_liquidity_preserves_component_dates_and_units(self):
        with closing(sqlite3.connect(self.path)) as c,c:
            c.executemany('INSERT INTO market_indicators VALUES (?,?,?,?)',[
                ('macro_fed_bs','2026-10-01',7000000,'SECRET'),
                ('macro_tga','2026-10-01',900000,'SECRET'),
                ('macro_rrp','2026-10-02',100,'SECRET'),
                ('macro_rrp','2026-10-03',200,'SECRET'),
                ('macro_m2','2026-09-01',23000,'SECRET')])
        data=self.client.get('/api/spine/macro/public').json()
        net=next(x for x in data['items'] if x['key']=='net_liq')
        self.assertEqual(net['value'],5.9)
        self.assertEqual(net['as_of'],'2026-10-03')
        self.assertEqual([x['as_of'] for x in net['sources']],['2026-10-01','2026-10-01','2026-10-03'])
        self.assertIsNone(net['comparison_date'])
        self.assertEqual(next(x for x in data['items'] if x['key']=='m2')['value'],23)

    def test_unavailable_snapshot_is_503_and_malformed_receipt_is_invalid(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as failure:
            self.original_connection(self.path.parent/'missing.sqlite')
        self.assertEqual(failure.exception.status_code,503)
        for malformed in ('not json', '[]', '{"sha256":123}'):
            with closing(sqlite3.connect(self.path)) as c,c:
                c.execute("UPDATE source_receipts SET receipt_json=? WHERE key='us2y'",(malformed,))
            response=self.client.get('/api/spine/macro/public')
            self.assertEqual(response.status_code,200)
            self.assertEqual(next(x for x in response.json()['coverage'] if x['key']=='us2y')['status'],'invalid')
