"""Actual publication revisions gate both evidence text and aggregate counts."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import spine_feed
from security.public_documents import PublicDocuments
from security.publication_store import PublicationStore
from security.public_company_evidence import stored_evidence
from security import public_us_season
from security.access_boundary import PublicAccessBoundary, PUBLIC_ROUTE_POLICIES

class PublicEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.path=root/'us.sqlite';self.source=root/'app.sqlite'
        with closing(sqlite3.connect(self.path)) as c, c:
            c.executescript('''CREATE TABLE public_us_companies(ticker,company_name,sector,market_cap,fiscal_year_end);
                INSERT INTO public_us_companies VALUES('NVDA','Nvidia','semis',1,'01-31');
                CREATE TABLE public_company_evidence(ticker,doc_id,fingerprint,PRIMARY KEY(ticker,doc_id));''')
        with closing(sqlite3.connect(self.source)) as c, c:
            c.executescript('''CREATE TABLE raw_documents(id,title,source_type,url,published_at,markdown,raw_content,media_json);
                INSERT INTO raw_documents VALUES(1,'Revenue','earnings_release','https://www.sec.gov/example','2026-11-14','Reviewed revenue',NULL,'[]');
                INSERT INTO raw_documents VALUES(2,'Private','note',NULL,'2026-11-14','private canary',NULL,'[]');''')
        self.store=PublicationStore(root/'approval.sqlite');self.store.initialize()
        self.service=PublicDocuments(self.source,root,self.store)
        fp=self.service.capture(1).fingerprint
        self.store.approve(1,fp,0,'test','Synthetic fixture')
        with closing(sqlite3.connect(self.path)) as c, c:
            c.executemany('INSERT INTO public_company_evidence VALUES(?,?,?)',[('NVDA',1,fp),('NVDA',2,'unapproved')])

    def read(self,**kw):
        return stored_evidence('NVDA',path=self.path,service=self.service,
            now=datetime(2026,11,15,tzinfo=timezone.utc),**kw)

    def assert_empty(self):
        r=self.read();self.assertEqual(r['items'],[]);self.assertEqual(r['total'],0)
        self.assertEqual(r['coverage'],[]);self.assertEqual(r['flow']['sources'],[])
        self.assertEqual(sum(d['count'] for d in r['flow']['days']),0)

    def test_approved_only_counts_and_filters(self):
        r=self.read();self.assertEqual(r['total'],1);self.assertEqual(r['coverage'][0]['count'],1)
        self.assertEqual(sum(d['count'] for d in r['flow']['days']),1)
        self.assertNotIn('private canary',str(r));self.assertEqual(self.read(q='missing')['total'],0)
        self.assertEqual(self.read(source='note')['total'],0)
        self.assertEqual(self.read(page=2,size=1)['items'],[])

    def test_revocation_removes_body_and_aggregates(self):
        self.store.revoke(1,1,'test');self.assert_empty()

    def test_modified_and_reapproved_document_requires_reviewed_company_link(self):
        with closing(sqlite3.connect(self.source)) as c, c:c.execute("UPDATE raw_documents SET markdown='Changed' WHERE id=1")
        self.assert_empty()
        self.store.approve(1,self.service.capture(1).fingerprint,1,'test','New fixture')
        self.assert_empty()

    def test_revocation_during_capture_removes_all_aggregates(self):
        original = self.service.published
        def revoke_after_capture(*args, **kwargs):
            snapshot = original(*args, **kwargs)
            self.store.revoke(1, 1, 'test')
            return snapshot
        with patch.object(self.service, 'published', side_effect=revoke_after_capture):
            self.assert_empty()

    def test_http_scope_readonly_and_no_private_lookup(self):
        app=FastAPI();app.include_router(spine_feed.router)
        app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies={('GET','/api/spine/feed/company-evidence'):'public'})
        with TestClient(app,base_url='https://beta.example') as client,patch.object(public_us_season,'DB_PATH',self.path),patch.object(PublicDocuments,'from_environment',return_value=self.service),patch.object(spine_feed,'get_connection',side_effect=AssertionError('private DB')):
            r=client.get('/api/spine/feed/company-evidence?company=NVDA&market=us');self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()['total'],1)
            self.assertEqual(client.get('/api/spine/feed/company-evidence?company=NVDA&market=us&start=2026-02-30').status_code,422)
            self.assertEqual(client.get('/api/spine/feed/company-evidence?company=NVDA&market=us&start=2026-11-15&end=2026-11-14').status_code,422)
            self.assertEqual(client.get('/api/spine/feed/company-evidence?company=NVDA&market=kr').status_code,404)
            self.assertEqual(client.get('/api/spine/feed/company-evidence?company=SECRET&market=us').status_code,404)
            self.assertEqual(client.post('/api/spine/feed/company-evidence/summary',json={}).status_code,404)
