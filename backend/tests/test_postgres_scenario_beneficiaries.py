"""Scenario beneficiaries use the same market generation as the candidate."""
import sqlite3
import unittest
from psycopg.types.json import Jsonb
from pipeline.beneficiary import resolve_and_enrich
from pipeline.postgres_scenario_beneficiaries_fixture import import_beneficiary_aux,resolve_beneficiaries,BeneficiarySnapshotConflict
import tests.test_postgres_ingest_fixture as fixtures


class ScenarioBeneficiariesTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.IngestFixtureTests('runTest');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.source=sqlite3.connect(':memory:');self.source.row_factory=sqlite3.Row;self.addCleanup(self.source.close)
        self.source.executescript('''
          CREATE TABLE entities(id INTEGER,type TEXT,name TEXT,aliases TEXT);
          CREATE TABLE companies(stock_code TEXT,corp_name TEXT);
          CREATE TABLE industry_groups(id INTEGER,name TEXT);
          CREATE TABLE industry_members(id INTEGER,group_id INTEGER,stock_code TEXT);
          CREATE TABLE fundamentals(id INTEGER,stock_code TEXT,trade_date TEXT,per REAL,pbr REAL);
          CREATE TABLE stock_prices(id INTEGER PRIMARY KEY,stock_code TEXT,trade_date TEXT,close REAL,market_cap REAL);
          CREATE INDEX price_idx ON stock_prices(stock_code,trade_date DESC);
          INSERT INTO entities VALUES(1,'company','가상 기업','AAA'),(2,'company','둘째 기업','BBB');
          INSERT INTO companies VALUES('AAA','가상 기업'),('BBB','둘째 기업');
          INSERT INTO industry_groups VALUES(1,'시험 그룹');
          INSERT INTO industry_members VALUES(1,1,'AAA');
          INSERT INTO fundamentals VALUES(1,'AAA','2026-01-01',10,2),(2,'AAA','2026-02-01',12,3);
          INSERT INTO stock_prices VALUES(1,'AAA','2025-12-01',50,1000),(2,'AAA','2026-01-01',100,2000),
            (3,'AAA','2026-02-01',120,2400),(4,'BBB','2026-01-01',100,1000),(5,'BBB','2026-02-01',90,900);
        ''')
        self.source.execute('PRAGMA query_only=ON');self.source.execute('BEGIN')
        with self.fixture.pg() as pg:
            pg.execute("INSERT INTO snapshot_metadata(singleton,snapshot_at,source_observed_at,document_count,list_row_count,generation_id) VALUES(true,'fixture',now(),0,0,'00000000-0000-0000-0000-000000000001')")
            pg.execute('CREATE TABLE sector_market_metadata(singleton BOOLEAN PRIMARY KEY,generation_id UUID,linked_document_generation BOOLEAN)')
            pg.execute("INSERT INTO sector_market_metadata VALUES(true,'00000000-0000-0000-0000-000000000001',true)")
            pg.execute('CREATE TABLE sector_market_prices(id BIGINT PRIMARY KEY,stock_code TEXT,trade_date TEXT,close BIGINT,market_cap BIGINT)')
            pg.execute('CREATE TABLE sector_market_companies(ordinal BIGINT,stock_code TEXT,corp_name TEXT)')
            for row in self.source.execute('SELECT id,stock_code,trade_date,close,market_cap FROM stock_prices'):pg.execute('INSERT INTO sector_market_prices VALUES(%s,%s,%s,%s,%s)',tuple(row))
            for i,row in enumerate(self.source.execute('SELECT stock_code,corp_name FROM companies')):pg.execute('INSERT INTO sector_market_companies VALUES(%s,%s,%s)',(i,*tuple(row)))
            pg.execute("INSERT INTO legacy_snapshot_tables VALUES('entities',%s,'fixture',2)",(Jsonb([]),))
            for i,row in enumerate(self.source.execute('SELECT * FROM entities')):pg.execute("INSERT INTO legacy_snapshot_rows VALUES('entities',%s,%s)",(i,Jsonb(dict(row))))

    def test_matches_original_calculations_and_unresolved_company(self):
        picks=[{'name':'가상 기업','rel':'수혜','reason':'시험'},{'name':'없는 기업','rel':'피해','reason':'시험'}]
        expected=resolve_and_enrich(self.source,picks)
        with self.fixture.pg() as pg:counts=import_beneficiary_aux(self.source,pg)
        self.assertEqual(counts,{'fundamentals':1,'industry_groups':1,'industry_members':1})
        actual=resolve_beneficiaries(self.fixture.pg,picks)
        self.assertEqual(actual,expected)
        self.assertEqual(actual[0]['per'],12.0)
        self.assertEqual(actual[0]['universe_groups'],['시험 그룹'])
        self.assertIsNone(actual[1]['stock_code'])

    def test_rejects_different_market_generation(self):
        with self.fixture.pg() as pg:import_beneficiary_aux(self.source,pg)
        with self.fixture.pg() as pg:pg.execute("UPDATE sector_market_metadata SET generation_id='00000000-0000-0000-0000-000000000002'")
        with self.assertRaises(BeneficiarySnapshotConflict):resolve_beneficiaries(self.fixture.pg,[{'name':'가상 기업'}])

    def test_scenario_runtime_uses_pg_beneficiary_and_explicit_graph_writer(self):
        from types import SimpleNamespace
        from pipeline import scenario
        from pipeline.postgres_scenario_runtime_fixture import PostgreSQLScenarioRuntime
        with self.fixture.pg() as pg:import_beneficiary_aux(self.source,pg)
        graph=[]
        inputs=SimpleNamespace(gather=lambda event,limit:([],[],[]))
        def model(prompt,**kw):
            return SimpleNamespace(text='{"scenario":"시험","beneficiaries":[{"name":"가상 기업","rel":"수혜"}],"causal":{"nodes":[],"edges":[]}}')
        def writer(causal,**kw):graph.append((causal,kw))
        runtime=PostgreSQLScenarioRuntime(self.fixture.pg,inputs=inputs,run_llm=model,graph_writer=writer)
        result=scenario.build_scenario('가상 사건',report_context='기존 결산',runtime=runtime)
        self.assertEqual(result['beneficiaries'][0]['stock_code'],'AAA')
        self.assertEqual(result['beneficiaries'][0]['per'],12.0)
        self.assertEqual(graph[0][1],{'conf_cap':0.5,'source_status':'scenario'})
