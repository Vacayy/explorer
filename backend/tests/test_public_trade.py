"""Stored-only public customs projections and pure legacy arithmetic parity."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.public_trade import router
from security.access_boundary import PublicAccessBoundary,PUBLIC_ROUTE_POLICIES
from security.public_trade import stored_trade,trade_connection,project,month_before
from pipeline import trade_metrics
from pipeline.trade_catalog import DEFAULT_FOLLOWS


class PublicTradeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'trade.sqlite'
        with closing(sqlite3.connect(self.path)) as c,c:
            c.executescript('''CREATE TABLE trade_stats(hs_code,period,export_usd,import_usd,fetched_at,secret,
                 UNIQUE(hs_code,period));CREATE TABLE trade_follow(hs_code,item_name,group_label,active);
                 CREATE TABLE trade_beneficiaries(secret);INSERT INTO trade_beneficiaries VALUES('PRIVATE_CANARY');
                 INSERT INTO trade_follow VALUES('private','SECRET','PRIVATE_CANARY',1);''')
            for back in range(260):
                p=month_before('2026-10',back)
                if back!=1:c.execute('INSERT INTO trade_stats VALUES(?,?,?,?,?,?)',('854232',p,20e6+back*1000,4e6,'2026-11-01','PRIVATE_CANARY'))
            c.execute("INSERT INTO trade_stats VALUES('PRIVATE','2026-11',999,999,'SECRET','CANARY')")
        app=FastAPI();app.include_router(router)
        app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies={k:v for k,v in PUBLIC_ROUTE_POLICIES.items() if k[1]=='/api/public/trade'},
            service_factory=lambda:SimpleNamespace(identities=None,config=SimpleNamespace(public_origin='https://beta.example')))
        self.client=TestClient(app,base_url='https://beta.example');self.addCleanup(self.client.close)
        p=patch('config.DB_PATH',self.path);p.start();self.addCleanup(p.stop)

    def test_public_highlights_coverage_and_no_private_follows(self):
        from security.public_trade import stored_highlights
        from routers.spine_trade import router as legacy_router
        before=self.path.read_bytes()
        with patch.object(trade_metrics,'get_connection',side_effect=AssertionError('private follows')):
            result=stored_highlights(path=self.path)
            self.assertEqual(result['scope'],'public_catalog')
            self.assertEqual(result['observed_count'],1)
            self.assertTrue(result['partial'])
            self.assertEqual(result['total_usd'],20e6)
            self.assertTrue(any(g['value'] is None for g in result['groups']))
            empty=stored_highlights(period='1990-01',path=self.path)
            self.assertIsNone(empty['total_usd'])
            self.assertNotIn('PRIVATE_CANARY',str(result))
        self.assertEqual(before,self.path.read_bytes())
        app=FastAPI();app.include_router(legacy_router)
        app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies={('GET','/api/spine/trade/highlights'):'public'})
        with TestClient(app,base_url='https://beta.example') as client:
            self.assertEqual(client.get('/api/spine/trade/highlights?limit=100').status_code,200)
            self.assertEqual(client.get('/api/spine/trade/highlights?limit=101').status_code,422)
            self.assertEqual(client.get('/api/spine/trade/highlights?rank=private').status_code,422)

    def test_actual_http_bounds_gap_and_private_independence(self):
        before=self.path.read_bytes()
        with patch.object(trade_metrics,'get_connection',side_effect=AssertionError('hidden DB')):
            r=self.client.get('/api/public/trade?months=24');self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.path.read_bytes(),before)
        data=r.json();self.assertEqual(data['period'],'2026-10');self.assertEqual(len(data['rows']),11)
        self.assertLessEqual(len(data['periods']),240)
        row=data['rows'][0];self.assertEqual(len(row['series']),24)
        self.assertIsNone(row['series'][-2]['value']);self.assertIsNone(row['metrics']['mom'])
        self.assertIsNone(row['metrics']['ma12'])
        self.assertEqual(row['metrics']['balance_usd'],row['metrics']['export_usd']-row['metrics']['import_usd'])
        self.assertTrue(any(p['ma12'] is not None for p in row['series']))
        self.assertEqual(data['total']['observed_count'],1);self.assertEqual(data['total']['total_count'],11)
        self.assertTrue(data['total']['partial']);self.assertNotIn('CANARY',r.text)
        self.assertEqual(r.headers['cache-control'],'no-store')
        with closing(sqlite3.connect(self.path)) as c,c:
            c.execute("UPDATE trade_follow SET item_name='CHANGED_PRIVATE'")
            c.execute('DELETE FROM trade_beneficiaries')
        self.assertEqual(self.client.get('/api/public/trade?months=24').json(),data)
        old=self.client.get('/api/public/trade?period=2025-10&flow=import&months=60')
        self.assertEqual(old.status_code,200,old.text);self.assertEqual(old.json()['valuation'],'CIF')
        self.assertEqual(old.json()['periods'][0],'2026-10')
        self.assertEqual(old.json()['rows'][0]['series'][-1]['period'],'2025-10')
        for q in ('months=25','months=0','flow=all','period=2026-13','period=9999-01','period=abc'):
            self.assertEqual(self.client.get('/api/public/trade?'+q).status_code,422,q)
        self.assertEqual(self.client.post('/api/public/trade').status_code,404)

    def test_authorizer_blocks_private_columns_writes_and_functions(self):
        with closing(trade_connection(self.path)) as conn:
            for sql in ('SELECT * FROM trade_follow','SELECT secret FROM trade_stats',
                        'DELETE FROM trade_stats','PRAGMA table_info(trade_stats)',
                        "ATTACH ':memory:' AS other",'SELECT random()'):
                with self.assertRaises(sqlite3.DatabaseError,msg=sql):conn.execute(sql)

    def test_missing_zero_corrected_values_and_no_future_metric_input(self):
        with closing(sqlite3.connect(self.path)) as c,c:
            c.execute("DELETE FROM trade_stats WHERE period='2025-10'")
        row=stored_trade(path=self.path)['rows'][0]
        self.assertEqual(row['metrics']['flag'],'none');self.assertIn('누락',row['metrics']['reason'])
        self.assertIsNone(row['metrics']['contribution'])
        with closing(sqlite3.connect(self.path)) as c,c:
            c.execute("INSERT INTO trade_stats VALUES('854232','2025-10',0,0,'2026-11-01',NULL)")
        self.assertEqual(stored_trade(path=self.path)['rows'][0]['metrics']['flag'],'new')
        self.assertIn('확인되지 않았습니다',stored_trade(path=self.path)['rows'][0]['metrics']['reason'])
        old=stored_trade(period='2025-10',path=self.path)
        with closing(sqlite3.connect(self.path)) as c,c:
            c.execute("UPDATE trade_stats SET export_usd=100000000 WHERE period='2026-10'")
        self.assertEqual(stored_trade(period='2025-10',path=self.path),old)
        self.assertEqual(stored_trade(path=self.path)['rows'][0]['metrics']['value'],100000000)
        with closing(sqlite3.connect(self.path)) as c,c:c.execute('DELETE FROM trade_stats')
        empty=stored_trade(path=self.path)
        self.assertTrue(empty['empty']);self.assertIsNone(empty['total']['value']);self.assertEqual(empty['rows'],[])

    def test_pure_existing_table_parity_and_nested_aggregation(self):
        with closing(sqlite3.connect(':memory:')) as c:
            c.row_factory=sqlite3.Row
            c.executescript('''CREATE TABLE trade_stats(hs_code,period,export_usd,import_usd,export_wt,import_wt);
                CREATE TABLE trade_follow(hs_code,item_name,group_label,active);''')
            catalog=[{'hs_code':code,'item_name':code,'group_label':'group'} for code in ('85','854232')]
            raw={code:[{'period':month_before('2026-10',b),'export_usd':float(100+b),'import_usd':5.0} for b in range(30,-1,-1)] for code in ('85','854232')}
            c.executemany('INSERT INTO trade_follow VALUES(?,?,?,1)',[(r['hs_code'],r['item_name'],r['group_label']) for r in catalog])
            c.executemany('INSERT INTO trade_stats VALUES(?,?,?,?,NULL,NULL)',[(code,r['period'],r['export_usd'],r['import_usd']) for code,rs in raw.items() for r in rs])
            class Borrowed:
                def execute(_, *args):return c.execute(*args)
                def close(_):pass
            periods=trade_metrics.periods(c)
            with patch.object(trade_metrics,'get_connection',return_value=Borrowed()):legacy=trade_metrics.table()
            with patch.object(trade_metrics,'get_connection',side_effect=AssertionError('hidden DB')):
                self.assertEqual(trade_metrics.table_from_inputs(catalog,raw,periods),legacy)
            with patch('security.public_trade.DEFAULT_FOLLOWS',[('85','85','group'),('854232','854232','group')]):
                out=project(raw,{},'export','2026-10','2026-10',24,periods)
            self.assertEqual(out['total']['value'],100)
            self.assertEqual(out['total']['total_count'],1)
            self.assertEqual(out['groups'][0]['value'],100)
            self.assertEqual(out['rows'][1]['nested_in'],'85')

    def test_empty_selected_month_and_group_coverage_do_not_invent_zero(self):
        for period in ('2026-11','1900-01'):
            out=stored_trade(period=period,path=self.path)
            self.assertTrue(out['empty']);self.assertTrue(out['partial'])
            self.assertIsNone(out['total']['value']);self.assertEqual(out['total']['observed_count'],0)
            self.assertTrue(all(g['value'] is None for g in out['groups']))
            self.assertTrue(all(r['metrics']['value'] is None for r in out['rows']))
        with closing(sqlite3.connect(self.path)) as c,c:
            c.execute("UPDATE trade_stats SET fetched_at='PRIVATE_TIMESTAMP_CANARY'")
        out=stored_trade(path=self.path)
        self.assertIsNone(out['fetched_at']);self.assertNotIn('CANARY',str(out))
        groups={g['group_label']:g for g in out['groups']}
        self.assertEqual(groups['반도체']['observed_count'],1)
        self.assertEqual(groups['반도체']['total_count'],2)
        self.assertTrue(groups['반도체']['partial'])
        self.assertIsNone(groups['IT']['value'])

    def test_240_month_numeric_bound_and_no_collector_import(self):
        original=trade_metrics.derive;lengths=[]
        def bounded(raw,flow):
            lengths.append(len(raw));return original(raw,flow)
        with patch('security.public_trade.derive',side_effect=bounded):
            out=stored_trade(path=self.path)
        self.assertLessEqual(max(lengths),240)
        self.assertEqual(out['periods'][-1],month_before('2026-10',239))
        # Catalog module is importable without the network/LLM trade collector.
        import subprocess,sys
        result=subprocess.run([sys.executable,'-c',
            "import sys; from security.public_trade import stored_trade; assert 'pipeline.trade' not in sys.modules"],
            capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_cross_group_children_excluded_from_all_aggregate_denominators(self):
        catalog=[('85','Parent','A'),('854232','Child','B')]
        raw={code:[{'period':'2026-10','export_usd':value}] for code,value in [('85',100),('854232',60)]}
        with patch('security.public_trade.DEFAULT_FOLLOWS',catalog):
            out=project(raw,{},'export','2026-10','2026-10',24,['2026-10'])
        groups={g['group_label']:g for g in out['groups']}
        self.assertEqual(out['total']['value'],100)
        self.assertEqual(groups['A']['value'],100)
        self.assertIsNone(groups['B']['value'])
        self.assertEqual(groups['B']['total_count'],0)
        self.assertEqual(sum(g['value'] or 0 for g in out['groups']),out['total']['value'])
        self.assertEqual(out['rows'][1]['metrics']['value'],60)

    def test_same_latest_month_historical_revision_recomputes_yoy_and_average(self):
        # Complete the only gap so the rolling average is observable.
        with closing(sqlite3.connect(self.path)) as c,c:
            c.execute("INSERT INTO trade_stats VALUES('854232','2026-09',20000000,4000000,'2026-11-01',NULL)")
        before=stored_trade(path=self.path)
        with closing(sqlite3.connect(self.path)) as c,c:
            c.execute("UPDATE trade_stats SET export_usd=export_usd*2 WHERE period IN ('2025-10','2026-08')")
        after=stored_trade(path=self.path)
        self.assertEqual(after['latest_period'],before['latest_period'])
        self.assertEqual(after['period'],before['period'])
        old,new=before['rows'][0]['metrics'],after['rows'][0]['metrics']
        self.assertEqual(old['value'],new['value'])
        self.assertNotEqual(old['yoy'],new['yoy'])
        self.assertNotEqual(old['ma12'],new['ma12'])
