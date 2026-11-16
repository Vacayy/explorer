"""Actual public financial route against isolated stored data and private canaries."""
from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import financials, companies
from services import dart_service
from security import public_financials as public
from security.access_boundary import PublicAccessBoundary


class PublicFinancialTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'db.sqlite'
        conn = sqlite3.connect(self.path)
        conn.executescript('''CREATE TABLE companies(stock_code, corp_code, private_note, corp_name, market, sector);
            INSERT INTO companies VALUES ('111111','corp','PRIVATE_CANARY','Fixture Corp','KOSPI','Test'), ('222222','empty','PRIVATE_CANARY','Empty Corp',NULL,NULL);
            CREATE TABLE private_notes(body); INSERT INTO private_notes VALUES ('PRIVATE_CANARY');
            CREATE TABLE financial_statements(corp_code, fs_div, sj_div, bsns_year, reprt_code, account_nm, thstrm_amount, ord, private_note);''')
        for fd, amount in [('CFS','100'), ('OFS','900')]:
            conn.execute('INSERT INTO financial_statements VALUES (?,?,?,?,?,?,?,?,?)',
                         ('corp',fd,'IS',datetime.now().year-1,'11011','매출액',amount,1,'PRIVATE_CANARY'))
        conn.commit(); conn.close()
        app = FastAPI(); app.include_router(financials.router); app.include_router(companies.router)
        app.add_middleware(PublicAccessBoundary, routes=app.router.routes,
                           policies={('GET','/api/financials/{stock_code}'): 'public',
                                     ('GET','/api/companies/search'): 'public',
                                     ('GET','/api/companies/{stock_code}'): 'public'})
        self.client = TestClient(app); self.addCleanup(self.client.close)
        self.addCleanup(patch.stopall)
        patch.object(public, 'financial_connection', side_effect=lambda: self.connection()).start()
        patch.object(companies, 'financial_connection', side_effect=lambda: self.connection()).start()
        patch.object(companies, 'get_connection', side_effect=AssertionError('private companies DB')).start()
        patch.object(dart_service, 'get_connection', side_effect=AssertionError('private DB')).start()
        patch.object(financials, 'fetch_financial_statements', side_effect=AssertionError('collector')).start()

    def connection(self):
        # Resolve the actual function instead of the patched public entry point.
        return self.original_connection(self.path)

    original_connection = staticmethod(public.financial_connection)

    def test_public_forces_stored_read_and_preserves_database(self):
        before = self.path.read_bytes()
        for option in ('', '?stored_only=false', '?stored_only=true'):
            response = self.client.get('/api/financials/111111' + option)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['rows'][0]['values'], ['100'])
            self.assertEqual(response.json()['fs_div'], 'CFS')
            self.assertNotIn('PRIVATE_CANARY', response.text)
            self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(before, self.path.read_bytes())

    def test_missing_company_and_empty_data_are_distinct(self):
        self.assertEqual(self.client.get('/api/financials/333333').status_code, 404)
        r = self.client.get('/api/financials/222222')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['rows'], [])

    def test_whole_response_fallback_and_explicit_ofs(self):
        self.assertEqual(self.client.get('/api/financials/111111?fs_div=OFS').json()['rows'][0]['values'], ['900'])
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM financial_statements WHERE fs_div='CFS'")
        r = self.client.get('/api/financials/111111').json()
        self.assertEqual(r['fs_div'], 'OFS')
        self.assertEqual(r['rows'][0]['values'], ['900'])

    def test_partial_cfs_does_not_switch_to_complete_ofs_for_ttm(self):
        year = datetime.now().year - 1
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE financial_statements SET reprt_code='11013' WHERE fs_div='CFS'")
            for code, value in [('11013','100'), ('11012','200'), ('11014','300')]:
                conn.execute('INSERT INTO financial_statements VALUES (?,?,?,?,?,?,?,?,?)',
                             ('corp','OFS','IS',year,code,'매출액',value,1,'PRIVATE_CANARY'))
        r = self.client.get('/api/financials/111111?period=trailing').json()
        self.assertEqual(r['fs_div'], 'CFS')
        self.assertEqual(r['rows'], [])
        ofs = self.client.get('/api/financials/111111?period=trailing&fs_div=OFS').json()
        self.assertEqual(ofs['rows'][0]['values'], ['900'])

    def test_collect_and_unreviewed_income_flow_are_denied(self):
        self.assertEqual(self.client.post('/api/financials/111111/collect').status_code, 404)
        self.assertEqual(self.client.get('/api/financials/111111/income-flow').status_code, 404)
        self.assertEqual(self.client.get('/api/financials/111111?years=100').status_code, 422)

    def test_sql_rejects_private_fields_mutation_and_attach(self):
        conn = self.connection(); self.addCleanup(conn.close)
        for sql in ('SELECT private_note FROM companies', 'SELECT body FROM private_notes',
                    'SELECT private_note FROM financial_statements', 'SELECT name FROM sqlite_master',
                    'DELETE FROM companies', 'PRAGMA query_only=OFF', "ATTACH ':memory:' AS other"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                conn.execute(sql)

    def test_public_company_search_and_metadata_are_bounded_and_projected(self):
        before = self.path.read_bytes()
        r = self.client.get('/api/companies/search?q=Fixture')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()[0]['stock_code'], '111111')
        self.assertNotIn('PRIVATE_CANARY', r.text)
        self.assertEqual(self.client.get('/api/companies/111111').json()['corp_name'], 'Fixture Corp')
        self.assertEqual(self.client.get('/api/companies/333333').status_code, 404)
        self.assertEqual(self.client.get('/api/companies/search?q=x&limit=-1').status_code, 422)
        self.assertEqual(self.client.get('/api/companies/search?q=x&limit=1000').status_code, 422)
        self.assertEqual(before, self.path.read_bytes())

    def test_missing_database_is_not_created(self):
        missing = self.path.parent / 'missing.sqlite'
        with self.assertRaises(sqlite3.OperationalError): self.original_connection(missing)
        self.assertFalse(missing.exists())
