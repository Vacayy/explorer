from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import spine_us
from security.access_boundary import PublicAccessBoundary
from security import public_us_briefing as public
from security.public_documents import DocumentUnavailable


class StoredUsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/'stored.sqlite'
        with sqlite3.connect(self.path) as c:
            c.executescript('''CREATE TABLE us_briefings(trade_date TEXT,created_at TEXT,synthesis_json TEXT,model TEXT);
                CREATE TABLE us_movers(trade_date TEXT,rank INTEGER,ticker TEXT,name TEXT,close REAL,volume REAL,
                dollar_volume REAL,change_pct REAL,sector TEXT,industry TEXT,exchange TEXT,market_cap REAL,
                is_adr INTEGER,is_new INTEGER,fetched_at TEXT);
                CREATE TABLE job_runs(summary TEXT); INSERT INTO job_runs VALUES ('private-job-canary');''')
            for day in ['2026-11-12','2026-11-13']:
                c.execute('INSERT INTO us_briefings VALUES (?,?,?,?)',(day,day+' 22:00:00',json.dumps(dict(drivers='Stored macro '+day,
                    issues='Stored companies',key_points=['Stored point'],source_gaps=['private-error-canary'],
                    sources=[dict(n=1,doc_id=999,publisher='private-source-canary')])),'private-model-canary'))
            c.execute("INSERT INTO us_movers VALUES ('2026-11-13',1,'EXAMPLE','Example',10,100,1000,9,'Technology Services','Software','X',2000,0,1,'2026-11-13 22:00:00')")
        self.service=Mock();self.service.published.side_effect=DocumentUnavailable()

    def test_stored_body_numeric_rows_history_and_no_private_enrichment(self):
        before=self.path.read_bytes()
        with patch('pipeline.us_briefing._enrich_coverage', side_effect=AssertionError('private lookup')):
            result=public.stored_briefing(path=self.path,publications=self.service)
        self.assertEqual(result.trade_date,'2026-11-13')
        self.assertEqual(result.synthesis.drivers,'Stored macro 2026-11-13')
        self.assertEqual(result.movers[0].dollar_volume,1000)
        self.assertEqual(result.clusters[0].share_pct,100)
        self.assertEqual(result.synthesis.sources,[])
        self.assertNotIn('canary',result.model_dump_json())
        old=public.stored_briefing('2026-11-12',path=self.path,publications=self.service)
        self.assertEqual(old.status,'partial');self.assertIsNotNone(old.synthesis)
        self.assertEqual(len(public.briefing_dates(path=self.path)),2)
        self.assertEqual(before,self.path.read_bytes())

    def test_route_force_denied_and_stored_response_matches_model(self):
        app=FastAPI();app.include_router(spine_us.router)
        app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies={
            ('GET','/api/spine/us/briefing'):'public',('GET','/api/spine/us/briefing/list'):'public'})
        client=TestClient(app,base_url='https://beta.example');self.addCleanup(client.close)
        with patch.object(public,'DB_PATH',self.path),patch.object(public.PublicDocuments,'from_environment',return_value=self.service),patch('pipeline.us_briefing.build_briefing',side_effect=AssertionError('generation')):
            self.assertEqual(client.get('/api/spine/us/briefing?force=true').status_code,403)
            self.assertEqual(client.get('/api/spine/us/briefing').status_code,200)
            self.assertEqual(client.get('/api/spine/us/briefing/list').status_code,200)
            self.assertEqual(client.get('/api/spine/us/briefing/sources').status_code,404)
            self.assertEqual(client.get('/api/spine/us/briefing/list?limit=-1').status_code,422)

if __name__=='__main__': unittest.main()
