from contextlib import closing
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import company_profile as route
from security import public_company_profile as public, public_us_season, public_kr_season
from security.access_boundary import PublicAccessBoundary


class PublicCompanyProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'public.sqlite'
        self.profile=dict(id=1,stock_code='NVDA',version=1,created_at='2026-11-01T00:00:00Z',
            model=None,cost_usd=None,reason=None,source_count=1,overview='Stored company overview',
            sources=[dict(id=1,url='https://www.sec.gov/Archives/test',title='Filing',publisher='SEC',
                          published_at=None,kind='filing',excerpt='',fetched=True)],
            drivers=[dict(text='Stored business driver',source_ids=[1])],gaps=['Historical report, not live'])
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript('''CREATE TABLE public_us_companies(ticker,company_name,sector,market_cap,fiscal_year_end);
                INSERT INTO public_us_companies VALUES('NVDA','NVIDIA','semis',1,'01-31');
                INSERT INTO public_us_companies VALUES('AMAT','Applied Materials','semis',1,'10-31');
                CREATE TABLE public_company_profiles(ticker PRIMARY KEY,payload_json);
                CREATE TABLE company_profiles(reason);INSERT INTO company_profiles VALUES('private canary');''')
            conn.execute('INSERT INTO public_company_profiles VALUES(?,?)',('NVDA',json.dumps(self.profile)));conn.commit()

    def update(self,profile):
        with sqlite3.connect(self.path) as c:c.execute('UPDATE public_company_profiles SET payload_json=?',(json.dumps(profile),))

    def test_read_is_stored_and_does_not_touch_private_state(self):
        before=self.path.read_bytes()
        with patch.object(route.cp,'connect',side_effect=AssertionError('private db')),patch.object(route.cp,'research_company',side_effect=AssertionError('LLM')):
            p=public.stored_profile('nvda',path=self.path)
            self.assertEqual(p.overview,self.profile['overview']);self.assertEqual(p.gaps,self.profile['gaps'])
            self.assertIsNone(public.stored_profile('AMAT',path=self.path))
            with self.assertRaises(LookupError):public.stored_profile('PRIVATE',path=self.path)
        self.assertEqual(before,self.path.read_bytes())
        with closing(public_us_season.connection(self.path)) as c:
            with self.assertRaises(sqlite3.DatabaseError):c.execute('select reason from company_profiles').fetchall()
            with self.assertRaises(sqlite3.DatabaseError):c.execute('delete from public_company_profiles')

    def test_rejects_metadata_excerpt_unsafe_url_and_broken_citation(self):
        changes=[{'reason':'private canary'},{'model':'private model'},{'cost_usd':1},{'stock_code':'OTHER'},
                 {'source_count':2},{'drivers':[{'text':'bad citation','source_ids':[999]}]}]
        for change in changes:
            with self.subTest(change=change):
                self.update(dict(self.profile,**change))
                with self.assertRaises(ValueError):public.stored_profile('NVDA',path=self.path)
        for source_change in ({'excerpt':'unreviewed text'},{'url':'javascript:alert(1)'},{'url':'https://user:pass@example.com'},
                              {'url':'https://www.fool.com/article'}):
            self.update(dict(self.profile,sources=[dict(self.profile['sources'][0],**source_change)]))
            with self.assertRaises(ValueError):public.stored_profile('NVDA',path=self.path)

    def test_http_read_only_and_private_path_unchanged(self):
        app=FastAPI();app.include_router(route.router)
        app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies={('GET','/api/spine/company-profile/{code}'):'public'})
        with TestClient(app,base_url='https://beta.example') as client,patch.object(public_us_season,'DB_PATH',self.path),patch.object(route.cp,'connect',side_effect=AssertionError('private db')):
            r=client.get('/api/spine/company-profile/nvda?market=us');self.assertEqual(r.status_code,200)
            self.assertEqual(r.json()['profile']['overview'],self.profile['overview'])
            self.assertEqual(client.get('/api/spine/company-profile/AMAT?market=us').json()['profile'],None)
            self.assertEqual(client.get('/api/spine/company-profile/NVDA?market=kr').status_code,404)
            self.assertEqual(client.get('/api/spine/company-profile/UNKNOWN?market=us').status_code,404)
            self.assertEqual(client.post('/api/spine/company-profile/NVDA?market=us',json={'force':True}).status_code,404)
        private=FastAPI();private.include_router(route.router)
        with TestClient(private) as client,patch.object(route.cp,'connect') as connect,patch.object(route,'_company'),patch.object(route.cp,'latest_profile',return_value=dict(self.profile,reason='private reason',model='private model',cost_usd=1)):
            r=client.get('/api/spine/company-profile/NVDA?market=us');self.assertEqual(r.status_code,200)
            self.assertEqual(r.json()['profile']['reason'],'private reason');connect.return_value.close.assert_called_once()

class PublicKrCompanyProfileTests(PublicCompanyProfileTests):
    def test_kr_registry_and_official_metadata(self):
        profile=dict(self.profile,stock_code='000660',official_report=dict(rcept_no='20261114000123',report_nm='Quarterly report',rcept_dt='20261114',url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261114000123'))
        with closing(sqlite3.connect(self.path)) as c,c:
            c.executescript("CREATE TABLE companies(stock_code,corp_name);INSERT INTO companies VALUES('000660','Company');INSERT INTO companies VALUES('005930','Empty');")
            c.execute('INSERT INTO public_company_profiles VALUES(?,?)',('000660',json.dumps(profile)))
        before=self.path.read_bytes()
        got=public.stored_profile('000660',market='kr',path=self.path)
        self.assertEqual(got.official_report.rcept_no,'20261114000123')
        self.assertIsNone(public.stored_profile('005930',market='kr',path=self.path))
        for code in ['999999','NVDA']:
            with self.assertRaises(LookupError):public.stored_profile(code,market='kr',path=self.path)
        self.assertEqual(before,self.path.read_bytes())
        app=FastAPI();app.include_router(route.router)
        app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies={('GET','/api/spine/company-profile/{code}'):'public'})
        with TestClient(app) as client,patch.object(public_kr_season,'DB_PATH',self.path),patch.object(route.cp,'connect',side_effect=AssertionError('private DB')):
            r=client.get('/api/spine/company-profile/000660?market=kr');self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()['profile']['stock_code'],'000660')
            self.assertEqual(client.post('/api/spine/company-profile/000660?market=kr',json={}).status_code,404)
        profile['official_report']['url']='https://user:password@dart.fss.or.kr/'
        with closing(sqlite3.connect(self.path)) as c,c:c.execute('UPDATE public_company_profiles SET payload_json=? WHERE ticker=?',(json.dumps(profile),'000660'))
        with self.assertRaises(ValueError):public.stored_profile('000660',market='kr',path=self.path)
