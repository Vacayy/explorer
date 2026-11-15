"""Public KR map: supplied readonly DB, public labels, no private cache/runtime."""
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from models.industry import IndustryMapResponse, KrSectorMarketResponse
from pipeline import sector_rs, sector_view
from routers import spine_industry
from security.access_boundary import PublicAccessBoundary
from security.public_industry import kr_industry_connection


class PublicKrIndustryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fixture.sqlite'
        with sqlite3.connect(self.path) as conn:
            conn.executescript('''
                CREATE TABLE stock_prices(id INTEGER PRIMARY KEY, stock_code, trade_date, close, market_cap, UNIQUE(stock_code,trade_date));
                CREATE TABLE companies(stock_code, sector, private_note);
                CREATE TABLE sector_map(sector_name, group_name);
                CREATE TABLE sector_overrides(stock_code, sector, reason, source);
                CREATE TABLE entities(id, type, aliases, name, meta_json);
                CREATE TABLE entity_relations(src_id, dst_id, rel_type, private_note);
                CREATE TABLE sector_benchmark_prices(ticker, trade_date, close);
                CREATE TABLE sector_index(sector, trade_date, value);
                CREATE TABLE sector_benchmarks(sector, ticker, name, tracks, note);
                CREATE TABLE private_notes(body);
                INSERT INTO companies VALUES ('000001','반도체 제조업','private-canary'),('000002','통신업','private-canary'),('000003','custom','private-canary');
                INSERT INTO sector_map VALUES ('반도체 제조업','반도체·전자부품'),('통신업','통신'),('custom','private-group-canary');
                INSERT INTO sector_overrides VALUES ('000001','반도체·전자부품','private-reason-canary','manual');
                INSERT INTO sector_benchmarks VALUES ('반도체·전자부품','091160','private-name-canary','private-tracks-canary','private-note-canary');
                INSERT INTO private_notes VALUES ('private-canary');
                INSERT INTO entities VALUES (1,'company','000004','private-company-canary','private-meta-canary'),(2,'sector',NULL,'반도체 제조업','private-meta-canary');
                INSERT INTO entity_relations VALUES (1,2,'MEMBER_OF','private-edge-canary');
            ''')
            days = [(date(2026, 6, 1) + timedelta(days=i)).isoformat() for i in range(140)]
            conn.executemany('INSERT INTO stock_prices(stock_code,trade_date,close,market_cap) VALUES (?,?,?,?)',
                [(c,d,100+i*s,1000*s) for c,s in [('000001',1),('000002',2),('000003',3),('000004',1)] for i,d in enumerate(days)])
            conn.executemany('INSERT INTO sector_benchmark_prices VALUES (?,?,?)',
                [(t,d,100+i) for t in ('091160','^KS11') for i,d in enumerate(days)])
            conn.executemany('INSERT INTO sector_index VALUES (?,?,?)', [('통신',d,100+2*i) for i,d in enumerate(days)])
        with sqlite3.connect(self.path) as conn:
            conn.execute('ALTER TABLE companies ADD COLUMN corp_name TEXT')
            conn.execute("UPDATE companies SET corp_name='Public company'")
        app = FastAPI()
        app.include_router(spine_industry.router)
        app.add_middleware(PublicAccessBoundary, routes=app.router.routes, policies={('GET','/api/spine/industry/map'):'public', ('GET','/api/spine/industry/{sector}/market'):'public'})
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.conn_patch = patch('security.public_industry.kr_industry_connection', side_effect=lambda: kr_industry_connection(self.path))
        self.conn_patch.start()
        self.addCleanup(self.conn_patch.stop)

    def test_real_public_route_ignores_global_connections_cache_and_private_metadata(self):
        before = self.path.read_bytes()
        with patch.object(sector_rs, 'get_connection', side_effect=AssertionError('hidden connection')), \
             patch.object(sector_rs, 'compute_sector_map', side_effect=AssertionError('private cache')), \
             patch.object(sector_view, 'benchmarks', side_effect=AssertionError('arbitrary metadata')), \
             patch.object(spine_industry, '_runtime', side_effect=AssertionError('Peer runtime')), \
             patch('database.get_connection', side_effect=AssertionError('private connection')):
            response = self.client.get('/api/spine/industry/map')
        self.assertEqual(response.status_code, 200, response.text)
        data = IndustryMapResponse.model_validate(response.json())
        self.assertEqual({s.name for s in data.sectors}, {'반도체·전자부품','통신'})
        semis = next(s for s in data.sectors if s.name == '반도체·전자부품')
        self.assertEqual(semis.stocks, 2)  # company master + graph fallback
        self.assertEqual(semis.benchmark.name, 'KODEX 반도체')
        self.assertEqual(len(semis.series), 61)
        self.assertTrue(all(s.rs_long is not None for s in data.sectors))
        self.assertFalse(data.peers_available)
        self.assertEqual(data.outside_groups, [])
        self.assertNotIn('canary', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.path.read_bytes(), before)

    def test_private_changes_do_not_change_map_but_shared_classification_does(self):
        first = self.client.get('/api/spine/industry/map').json()
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE sector_overrides SET reason='another secret'")
            conn.execute("UPDATE sector_benchmarks SET note='another secret'")
            conn.execute("UPDATE entities SET meta_json='another secret'")
        self.assertEqual(self.client.get('/api/spine/industry/map').json(), first)
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE sector_overrides SET sector='통신' WHERE stock_code='000001'")
        changed = self.client.get('/api/spine/industry/map').json()
        self.assertNotEqual(changed, first)
        self.assertEqual(next(s for s in changed['sectors'] if s['name']=='통신')['stocks'], 2)

    def test_request_memo_is_separate_and_empty_map_keeps_contract(self):
        with sector_rs.snapshot_memo():
            sector_rs._memo.get()['2026-10-18'] = {'private': (999,999)}
            response = self.client.get('/api/spine/industry/map')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(response.json()['sectors']), 2)
        with sqlite3.connect(self.path) as conn: conn.execute('DELETE FROM stock_prices')
        data = IndustryMapResponse.model_validate(self.client.get('/api/spine/industry/map').json())
        self.assertEqual(data.sectors, [])
        self.assertIsNone(data.as_of)

    def test_sql_rejects_private_columns_freeform_metadata_and_writes(self):
        conn = kr_industry_connection(self.path)
        self.addCleanup(conn.close)
        for sql in ('SELECT body FROM private_notes','SELECT reason FROM sector_overrides',
                    'SELECT meta_json FROM entities','SELECT note FROM sector_benchmarks',
                    'DELETE FROM stock_prices','PRAGMA query_only=OFF',"ATTACH DATABASE ':memory:' AS other"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError): conn.execute(sql)

    def test_market_detail_uses_one_snapshot_without_private_detail_or_cache(self):
        before = self.path.read_bytes()
        with patch.object(sector_rs, 'get_connection', side_effect=AssertionError('hidden connection')), \
             patch.object(sector_rs, 'compute_sector_map', side_effect=AssertionError('private cache')), \
             patch.object(sector_view, 'sector_detail', side_effect=AssertionError('private detail')), \
             patch.object(sector_view, '_cached', side_effect=AssertionError('private cache')), \
             patch.object(spine_industry, '_runtime', side_effect=AssertionError('private runtime')):
            response = self.client.get('/api/spine/industry/반도체·전자부품/market')
        self.assertEqual(response.status_code,200,response.text)
        data = KrSectorMarketResponse.model_validate(response.json())
        self.assertEqual(data.stocks,len(data.constituents))
        self.assertEqual({x.stock_code for x in data.constituents},{'000001','000004'})
        self.assertAlmostEqual(sum(x.weight for x in data.constituents),100)
        self.assertTrue(data.series)
        self.assertEqual(data.benchmark.name,'KODEX 반도체')
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(before,self.path.read_bytes())
        self.assertFalse({'docs','overview','narratives','entity_id','data_links'} & response.json().keys())
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO private_notes VALUES ('private-document-follow-trade-canary')")
            conn.execute("UPDATE entities SET meta_json='private-profile-canary'")
            conn.execute("UPDATE sector_benchmarks SET name='private-canary'")
        self.assertEqual(self.client.get('/api/spine/industry/반도체·전자부품/market').json(),response.json())
        self.assertEqual(self.client.get('/api/spine/industry/private-group-canary/market').status_code,404)
        self.assertEqual(self.client.get('/api/spine/industry/반도체·전자부품').status_code,404)
        with sqlite3.connect(self.path) as conn: conn.execute('DELETE FROM stock_prices')
        self.assertEqual(self.client.get('/api/spine/industry/반도체·전자부품/market').status_code,404)
