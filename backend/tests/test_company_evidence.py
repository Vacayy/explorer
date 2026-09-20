"""Isolated company/time contracts. No production DB, collectors or generation."""
import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from pipeline.company_evidence import company_evidence
from services.dart_service import _build_financial_response

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.executescript('''
        CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,source_type TEXT,source_id TEXT,title TEXT,url TEXT,published_at TEXT,markdown TEXT);
        CREATE TABLE entities(id INTEGER,name TEXT,aliases TEXT,status TEXT);
        CREATE TABLE entity_links(doc_id INTEGER,entity_id INTEGER,link_type TEXT);
        CREATE TABLE companies(corp_code TEXT,stock_code TEXT);
        CREATE TABLE disclosures(rcp_no TEXT,corp_code TEXT,flr_nm TEXT,report_nm TEXT,dart_url TEXT,rcept_dt TEXT);
        INSERT INTO entities VALUES(1,'삼성전자','005930',NULL),(2,'타사','000001',NULL),(3,'삼성전자 복제','005930',NULL);
        INSERT INTO companies VALUES('corp','005930');
        INSERT INTO disclosures VALUES('1','corp','DART','실적 공시','','20260612');
        ''')
    def tearDown(self):self.c.close()
    def doc(self,id,ts,entity=1,text='실적'):
        self.c.execute('INSERT INTO raw_documents VALUES (?,?,?,?,?,?,?)',(id,'telegram','채널',text,'https://example.com',ts,text))
        self.c.execute('INSERT INTO entity_links VALUES (?,?,?)',(id,entity,'stock'))
    def read(self,**kwargs):
        with patch('pipeline.sources.source_names',return_value={}):
            return company_evidence(self.c,'005930',now=datetime(2026,6,20,tzinfo=timezone.utc),**kwargs)
    def test_timezone_close_unknown_and_after(self):
        self.doc(1,'2026-06-12T06:29:00Z') # 15:29 KST
        self.doc(2,'2026-06-12T06:31:00Z')
        self.doc(3,'2026-06-13')
        r=self.read(start='2026-06-12',end='2026-06-12',cutoff='close')
        self.assertEqual([d['id'] for d in r['items']],['doc:1'])
        self.assertEqual(r['uncertain_count'],1)
        r=self.read(start='2026-06-12',end='2026-06-12',cutoff='close',after=True)
        self.assertEqual({d['id']:d['status'] for d in r['items']},{'doc:1':'within','doc:2':'after','doc:3':'after','disclosure:1':'uncertain'})
    def test_day_end_inclusive_calendar_not_utc(self):
        self.doc(1,'2026-06-11T15:00:00Z');self.doc(2,'2026-06-12T14:59:59Z');self.doc(3,'2026-06-12T15:00:00Z')
        ids={d['id'] for d in self.read(start='2026-06-12',end='2026-06-12')['items']}
        self.assertEqual(ids,{'doc:1','doc:2','disclosure:1'})
    def test_company_search_scope_and_duplicate_links(self):
        self.doc(1,'2026-06-12',text='특별한 수주');self.doc(2,'2026-06-12',entity=2,text='특별한 수주')
        self.c.execute("INSERT INTO entity_links VALUES(1,3,'stock')")
        r=self.read(q='수주');self.assertEqual(r['total'],1);self.assertEqual(r['items'][0]['id'],'doc:1')
    def test_no_date_fallback_or_future_data_and_stable_pagination(self):
        self.doc(1,'');self.doc(2,'bad');self.doc(3,'2027-01-01');self.doc(4,'2026-06-12');self.doc(5,'2026-06-12')
        r=self.read(source='telegram',size=1);s=self.read(source='telegram',size=1,page=2)
        self.assertEqual(r['undated_count'],2);self.assertEqual(r['total'],2);self.assertTrue(r['has_more']);self.assertNotEqual(r['items'][0]['id'],s['items'][0]['id'])
    def test_search_literal_wildcards_and_invalid_range(self):
        self.doc(1,'2026-06-12',text='매출 10%');self.doc(2,'2026-06-12',text='매출')
        self.assertEqual(self.read(q='%')['total'],1)
        with self.assertRaises(ValueError):self.read(start='2026-06-20',end='2026-06-10')
    def test_us_dst_boundary(self):
        self.doc(1,'2026-06-12T19:59:00Z');self.doc(2,'2026-06-12T20:01:00Z')
        r=self.read(start='2026-06-12',end='2026-06-12',market='us',cutoff='close',source='telegram')
        self.assertEqual([d['id'] for d in r['items']],['doc:1'])

class FinancialTests(unittest.TestCase):
    def build(self,sj,values):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
        c.execute('CREATE TABLE financial_statements(corp_code TEXT,bsns_year INTEGER,reprt_code TEXT,fs_div TEXT,sj_div TEXT,account_nm TEXT,thstrm_amount TEXT,ord INTEGER)')
        for rc,v in zip(['11013','11012','11014','11011'],values):
            if v is not None:c.execute('INSERT INTO financial_statements VALUES(?,?,?,?,?,?,?,?)',('c',2025,rc,'CFS',sj,'영업이익',str(v),1))
        # Service closes its connection. Capture output before teardown.
        with patch('services.dart_service.get_connection',return_value=c):return _build_financial_response('c',sj,'quarterly',2025,2025,'CFS')
    def test_income_is_already_quarterly_including_loss_and_zero(self):
        r=self.build('IS',[100,-20,0,200]);self.assertEqual(r['rows'][0]['values'],['100','-20','0','120'])
    def test_missing_quarter_does_not_invent_q4(self):
        r=self.build('IS',[100,None,30,200]);self.assertNotIn('25.12',r['periods'])
    def test_cashflow_remains_cumulative(self):
        r=self.build('CF',[100,180,240,300]);self.assertEqual(r['rows'][0]['values'],['100','80','60','60'])
    def test_balance_sheet_is_point_in_time(self):
        r=self.build('BS',[100,180,240,300]);self.assertEqual(r['rows'][0]['values'],['100','180','240','300'])

if __name__=='__main__':unittest.main()
