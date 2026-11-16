"""Scenario evidence comes from the selected disposable PG snapshot."""
import unittest
from types import SimpleNamespace
from psycopg.types.json import Jsonb
from pipeline.postgres_scenario_inputs_fixture import ScenarioInputsFixture
import tests.test_postgres_ingest_fixture as fixtures


class ScenarioInputsTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.IngestFixtureTests('runTest');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        tables={
          'raw_documents':('CREATE TABLE raw_documents(id INTEGER,source_type TEXT,source_id TEXT,title TEXT,url TEXT,published_at TEXT,markdown TEXT)',[
              {'id':1,'source_type':'blog','source_id':'1','title':'자료','url':'https://public.example/a','published_at':'2026-01-01','markdown':'공개 문장'},
              {'id':2,'source_type':'telegram','source_id':'muted/1','title':'숨김','url':'','published_at':'2026-01-01','markdown':'숨긴 문장'}]),
          'telegram_channels':('CREATE TABLE telegram_channels(channel_name TEXT,is_active INTEGER)',[{'channel_name':'muted','is_active':0}]),
          'blog_sources':('CREATE TABLE blog_sources(url TEXT,is_active INTEGER)',[]),
          'entities':('CREATE TABLE entities(id INTEGER,name TEXT,type TEXT,status TEXT)',[{'id':1,'name':'가상 주제','type':'theme','status':'active'}]),
          'knowledge':('CREATE TABLE knowledge(id INTEGER,statement TEXT,epistemic_status TEXT,pace_layer TEXT,review_status TEXT,valid_to TEXT)',[{'id':1,'statement':'가상 지식','epistemic_status':'observed','pace_layer':'flow','review_status':'active','valid_to':None}]),
          'knowledge_evidence':('CREATE TABLE knowledge_evidence(knowledge_id INTEGER,stance TEXT,independent INTEGER,observed_at TEXT)',[{'knowledge_id':1,'stance':'support','independent':1,'observed_at':'2026-01-01'}]),
        }
        import sqlite3
        with self.fixture.pg() as pg:
            for name,(ddl,rows) in tables.items():
                tmp=sqlite3.connect(':memory:');tmp.execute(ddl);cols=[r[1] for r in tmp.execute('PRAGMA table_info('+name+')')];tmp.close()
                pg.execute('INSERT INTO legacy_snapshot_tables VALUES(%s,%s,%s,%s)',(name,Jsonb(cols),ddl,len(rows)))
                with pg.cursor() as cur:cur.executemany('INSERT INTO legacy_snapshot_rows VALUES(%s,%s,%s)',[(name,i,Jsonb(r)) for i,r in enumerate(rows)])

    def test_gather_respects_muted_sources_and_knowledge(self):
        calls=[]
        def search(query,*,k):calls.append((query,k));return SimpleNamespace(items=[{'doc_id':2},{'doc_id':1}])
        def embed(texts):return [[1.0,0.0] for _ in texts]
        provider=ScenarioInputsFixture(self.fixture.pg,search=search,embedder=embed)
        docs,knowledge,vocab=provider.gather('주제',limit=10)
        self.assertEqual([d['id'] for d in docs],[1])
        self.assertEqual([k['id'] for k in knowledge],[1])
        self.assertEqual(vocab,['가상 주제'])
        self.assertEqual(calls,[('주제',15)])
