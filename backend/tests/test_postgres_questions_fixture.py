"""Question capture reads only from its disposable PG snapshot."""
import sqlite3
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipeline.postgres_questions_fixture import import_questions,QuestionsFixture
from pipeline.postgres_chat_preview_fork import fork_chat_preview
from routers.postgres_questions_fixture import create_router
from tests.test_postgres_chat_preview_fork import ChatPreviewForkTests


class QuestionsFixtureTests(ChatPreviewForkTests):
    def setUp(self):
        super().setUp()
        self.q=sqlite3.connect(':memory:');self.addCleanup(self.q.close)
        self.q.executescript('''
        CREATE TABLE questions(id INTEGER PRIMARY KEY AUTOINCREMENT,text TEXT,narrative_id INTEGER,source_doc_id INTEGER,status TEXT,updated_at TEXT,lead_verdict TEXT,confirm_verdict TEXT,divergence TEXT,last_viewed_at TEXT,created_by TEXT,stock_code TEXT,verdict_summary TEXT,conviction REAL,edge_confirmed INTEGER);
        CREATE TABLE sub_questions(id INTEGER PRIMARY KEY,question_id INTEGER,text TEXT,verdict TEXT,falsifier TEXT);
        CREATE TABLE proxy_registry(id INTEGER PRIMARY KEY,key TEXT UNIQUE,sub_question_id INTEGER,label TEXT,modality TEXT,yes_direction TEXT,unit TEXT,tickers TEXT,extract_hint TEXT,active INTEGER);
        CREATE TABLE proxy_observations(id INTEGER PRIMARY KEY,proxy_id INTEGER,transcript_id INTEGER,observed_at TEXT,value_num REAL,value_text TEXT,direction TEXT,confidence REAL,source_type TEXT,source_id TEXT,created_at TEXT);
        CREATE TABLE question_reports(id INTEGER PRIMARY KEY,question_id INTEGER,body TEXT,inputs_hash TEXT,created_at TEXT);
        CREATE TABLE proxy_scans(proxy_id INTEGER,transcript_id INTEGER);
        CREATE TABLE scenarios(topic TEXT,event TEXT,answer TEXT,beneficiaries TEXT,created_at TEXT,question_id INTEGER);
        CREATE TABLE transcripts(id INTEGER PRIMARY KEY,raw_doc_id INTEGER,ticker TEXT,fiscal_year INTEGER,fiscal_period TEXT);
        CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,title TEXT,source_type TEXT);
        CREATE TABLE observations(id INTEGER PRIMARY KEY AUTOINCREMENT,entity_id INTEGER NOT NULL,date TEXT NOT NULL,metric TEXT NOT NULL,value REAL,unit TEXT,source TEXT,UNIQUE(entity_id,date,metric,source));
        CREATE TABLE transcript_follow(ticker TEXT PRIMARY KEY,company_name TEXT,entity_id INTEGER);
        INSERT INTO questions VALUES(1,'원래 질문',7,10,'active','2026-01-01','unknown','unknown',NULL,NULL,'user',NULL,NULL,NULL,0);
        INSERT INTO sub_questions VALUES(2,1,'하위 질문','unknown',NULL);
        INSERT INTO proxy_registry VALUES(3,'q1_signal_0',2,'관측','numeric','up','개',NULL,NULL,1);
        INSERT INTO transcripts VALUES(4,10,'ABC',2026,'Q1');
        INSERT INTO transcript_follow VALUES('ABC','가상 기업',42);
        INSERT INTO proxy_observations VALUES(5,3,4,'2026-01-01',1,NULL,'up',0.8,'transcript','4',NULL);
        INSERT INTO raw_documents VALUES(10,'자료','transcript');
        INSERT INTO scenarios VALUES('주제','사건','답변','[]','2026-01-01',1);
        CREATE TABLE entity_relations(id INTEGER PRIMARY KEY,narrative_id INTEGER,promoted_knowledge_id INTEGER,obs_confirmed_at TEXT,obs_confirmed_qid INTEGER);
        CREATE TABLE narrative_edge_evidence(id INTEGER PRIMARY KEY,narrative_id INTEGER,entity_relation_id INTEGER);
        CREATE TABLE knowledge(id INTEGER PRIMARY KEY,statement TEXT,epistemic_status TEXT);
        CREATE TABLE knowledge_falsifiers(id INTEGER PRIMARY KEY,knowledge_id INTEGER,condition TEXT,triggered_at TEXT);
        INSERT INTO entity_relations VALUES(1,7,9,NULL,NULL);
        INSERT INTO narrative_edge_evidence VALUES(15,7,1);
        INSERT INTO knowledge VALUES(9,'검증된 지식','verified');
        INSERT INTO question_reports VALUES(6,1,'저장 보고서','old-hash','2026-01-01');
        UPDATE sqlite_sequence SET seq=50 WHERE name='questions';
        ''')
        self.q.execute('PRAGMA query_only=ON');self.q.execute('BEGIN')

    def test_import_and_existing_question_http_contract(self):
        with self.target() as pg:counts=import_questions(self.q,pg)
        self.assertEqual((counts['questions'],counts['sub_questions'],counts['proxy_observations'],counts['question_reports']),(1,1,1,1))
        app=FastAPI();app.include_router(create_router(QuestionsFixture(self.target)))
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/spine/questions').json()[0]['sub_count'],1)
            tree=client.get('/api/spine/questions/1').json()
            self.assertEqual(tree['source_doc']['id'],10)
            self.assertEqual(tree['sub_questions'][0]['proxies'][0]['obs_count'],1)
            self.assertEqual(tree['scenario']['beneficiaries'],[])
            self.assertEqual(client.get('/api/spine/questions/proxy/3').json()['observations'][0]['source']['doc_id'],10)
            report=client.get('/api/spine/questions/1/synthesis').json()
            self.assertEqual(report['body'],'저장 보고서')
            self.assertTrue(report['stale'])
            self.assertEqual(client.get('/api/spine/questions/999/synthesis').status_code,404)
            self.assertEqual(client.get('/api/spine/questions/999').status_code,404)
            self.assertIsNotNone(client.get('/api/spine/questions/1').json()['last_viewed_at'])
            self.assertEqual(client.delete('/api/spine/questions/1').status_code,204)
            self.assertEqual(client.get('/api/spine/questions').json(),[])
            self.assertEqual(client.post('/api/spine/questions',json={'text':'새 질문'}).status_code,405)

    def test_read_transaction_required(self):
        self.q.rollback()
        with self.target() as pg, self.assertRaises(ValueError):import_questions(self.q,pg)

    def test_deleted_highest_id_sequence_is_preserved(self):
        from pipeline.postgres_questions_fixture import _projection
        with self.target() as pg:import_questions(self.q,pg)
        with _projection(self.target) as factory:
            conn=factory()
            try:self.assertEqual(conn.execute("SELECT seq FROM sqlite_sequence WHERE name='questions'").fetchone()[0],50)
            finally:conn.close()

    def test_decomposition_is_atomic_and_preserves_sequence(self):
        from pipeline.postgres_question_create_fixture import stage_plan
        with self.target() as pg:import_questions(self.q,pg)
        plan={'sub_questions':[{'text':'새 하위 질문','proxies':[{'label':'성장','modality':'numeric','tickers':'ABC'}]}]}
        result=stage_plan(self.target,'새 질문',plan)
        self.assertEqual(result['question_id'],51)
        self.assertTrue(result['numeric_extraction_needed'])
        self.assertTrue(result['rollup_needed'])
        store=QuestionsFixture(self.target)
        tree=store.detail(51)
        self.assertEqual(tree['sub_questions'][0]['proxies'][0]['tickers'],'ABC')
        self.assertEqual(len(store.listing()),2)
        with self.assertRaises(AttributeError):
            stage_plan(self.target,'실패해야 할 질문',{'sub_questions':[{'text':'임시','proxies':[None]}]})
        self.assertEqual(len(store.listing()),2)
        next_id=stage_plan(self.target,'다음 질문',{'sub_questions':[]})['question_id']
        self.assertEqual(next_id,52)

    def test_concurrent_decompositions_get_distinct_ids(self):
        from concurrent.futures import ThreadPoolExecutor
        from pipeline.postgres_question_create_fixture import stage_plan
        with self.target() as pg:import_questions(self.q,pg)
        def make(n):return stage_plan(self.target,f'질문 {n}',{'sub_questions':[{'text':f'하위 {n}','proxies':[]}]})['question_id']
        with ThreadPoolExecutor(max_workers=2) as pool:ids=list(pool.map(make,(1,2)))
        self.assertEqual(set(ids),{51,52})
        self.assertEqual(len(QuestionsFixture(self.target).listing()),3)

    def test_sentiment_uses_pg_search_and_daily_idempotence(self):
        from types import SimpleNamespace
        from psycopg.types.json import Jsonb
        from pipeline.postgres_question_sentiment_fixture import extract_sentiment
        with self.fixture.pg() as pg:
            for table in ('raw_documents','enrichments'):
                pg.execute('INSERT INTO legacy_snapshot_tables VALUES(%s,%s,%s,1) ON CONFLICT DO NOTHING',(table,Jsonb([]),'fixture'))
            pg.execute("INSERT INTO legacy_snapshot_rows VALUES('raw_documents',90001,%s)",(Jsonb({'id':10,'title':'원문'}),))
            pg.execute("INSERT INTO legacy_snapshot_rows VALUES('enrichments',90001,%s)",(Jsonb({'doc_id':10,'summary':'실험 요약'}),))
            pg.execute("INSERT INTO snapshot_metadata(singleton,snapshot_at,source_observed_at,document_count,list_row_count,generation_id) VALUES(true,'fixture',now(),1,1,'00000000-0000-0000-0000-000000000001') ON CONFLICT(singleton) DO NOTHING")
        with self.target() as pg:
            fork_chat_preview(self.source,pg,self.fixture.schema);import_questions(self.q,pg)
            pg.execute("UPDATE question_capture_rows SET row_data=jsonb_set(row_data,'{modality}',to_jsonb('sentiment'::text)) WHERE table_name='proxy_registry' AND row_data->>'id'='3'")
        calls=[]
        def search(q,*,k):calls.append(('search',k));return SimpleNamespace(items=[{'doc_id':10}])
        def model(prompt,**kw):calls.append(('llm',kw['task']));return SimpleNamespace(text='{"direction":"up","value_text":"호전"}')
        result=extract_sentiment(self.target,1,search=search,run_llm=model)
        self.assertEqual(result,{'extracted':1,'stale':0})
        self.assertEqual(extract_sentiment(self.target,1,search=search,run_llm=model)['extracted'],0)
        self.assertEqual(calls,[('search',8),('llm','proxy.sentiment')])
        tree=QuestionsFixture(self.target).detail(1)
        self.assertEqual(tree['sub_questions'][0]['proxies'][0]['obs_count'],2)
        self.assertEqual(tree['sub_questions'][0]['proxies'][0]['observations'][0]['direction'],'up')

    def test_sentiment_drops_result_if_proxy_changes_during_model_call(self):
        from types import SimpleNamespace
        from psycopg.types.json import Jsonb
        from pipeline.postgres_question_sentiment_fixture import extract_sentiment
        with self.fixture.pg() as pg:
            for table in ('raw_documents','enrichments'):
                pg.execute('INSERT INTO legacy_snapshot_tables VALUES(%s,%s,%s,1) ON CONFLICT DO NOTHING',(table,Jsonb([]),'fixture'))
            pg.execute("INSERT INTO legacy_snapshot_rows VALUES('raw_documents',90002,%s)",(Jsonb({'id':10,'title':'원문'}),))
            pg.execute("INSERT INTO legacy_snapshot_rows VALUES('enrichments',90002,%s)",(Jsonb({'doc_id':10,'summary':'요약'}),))
            pg.execute("INSERT INTO snapshot_metadata(singleton,snapshot_at,source_observed_at,document_count,list_row_count,generation_id) VALUES(true,'fixture',now(),1,1,'00000000-0000-0000-0000-000000000001') ON CONFLICT(singleton) DO NOTHING")
        with self.target() as pg:
            fork_chat_preview(self.source,pg,self.fixture.schema);import_questions(self.q,pg)
            pg.execute("UPDATE question_capture_rows SET row_data=jsonb_set(row_data,'{modality}',to_jsonb('sentiment'::text)) WHERE table_name='proxy_registry' AND row_data->>'id'='3'")
        def search(q,*,k):return SimpleNamespace(items=[{'doc_id':10}])
        def model(prompt,**kw):
            with self.target() as pg:
                pg.execute("UPDATE question_capture_rows SET row_data=jsonb_set(row_data,'{label}',to_jsonb('변경됨'::text)) WHERE table_name='proxy_registry' AND row_data->>'id'='3'")
            return SimpleNamespace(text='{"direction":"up","value_text":"호전"}')
        self.assertEqual(extract_sentiment(self.target,1,search=search,run_llm=model),{'extracted':0,'stale':1})
        self.assertEqual(QuestionsFixture(self.target).detail(1)['sub_questions'][0]['proxies'][0]['obs_count'],1)

    def test_sentiment_drops_result_if_source_summary_changes(self):
        from types import SimpleNamespace
        from psycopg.types.json import Jsonb
        from pipeline.postgres_question_sentiment_fixture import extract_sentiment
        with self.fixture.pg() as pg:
            for table in ('raw_documents','enrichments'):
                pg.execute('INSERT INTO legacy_snapshot_tables VALUES(%s,%s,%s,1) ON CONFLICT DO NOTHING',(table,Jsonb([]),'fixture'))
            pg.execute("INSERT INTO legacy_snapshot_rows VALUES('raw_documents',90003,%s)",(Jsonb({'id':10,'title':'원문'}),))
            pg.execute("INSERT INTO legacy_snapshot_rows VALUES('enrichments',90003,%s)",(Jsonb({'doc_id':10,'summary':'이전 요약'}),))
            pg.execute("INSERT INTO snapshot_metadata(singleton,snapshot_at,source_observed_at,document_count,list_row_count,generation_id) VALUES(true,'fixture',now(),1,1,'00000000-0000-0000-0000-000000000001') ON CONFLICT(singleton) DO NOTHING")
        with self.target() as pg:
            fork_chat_preview(self.source,pg,self.fixture.schema);import_questions(self.q,pg)
            pg.execute("UPDATE question_capture_rows SET row_data=jsonb_set(row_data,'{modality}',to_jsonb('sentiment'::text)) WHERE table_name='proxy_registry' AND row_data->>'id'='3'")
        def search(q,*,k):return SimpleNamespace(items=[{'doc_id':10}])
        def model(prompt,**kw):
            with self.fixture.pg() as pg:
                pg.execute("UPDATE legacy_snapshot_rows SET row_data=jsonb_set(row_data,'{summary}',to_jsonb('수정된 요약'::text)) WHERE table_name='enrichments' AND row_ordinal=90003")
            return SimpleNamespace(text='{"direction":"up"}')
        self.assertEqual(extract_sentiment(self.target,1,search=search,run_llm=model),{'extracted':0,'stale':1})

    def test_transcript_numeric_scans_are_idempotent_and_preserve_no_result(self):
        from types import SimpleNamespace
        from psycopg.types.json import Jsonb
        from pipeline.postgres_question_numeric_fixture import extract_numeric
        with self.fixture.pg() as pg:
            for table in ('raw_documents','transcripts'):
                pg.execute('INSERT INTO legacy_snapshot_tables VALUES(%s,%s,%s,2) ON CONFLICT DO NOTHING',(table,Jsonb([]),'fixture'))
            for i in (9,10):
                pg.execute("INSERT INTO legacy_snapshot_rows VALUES('raw_documents',%s,%s)",(91000+i,Jsonb({'id':100+i,'markdown':'가상의 컨콜 본문'})))
                pg.execute("INSERT INTO legacy_snapshot_rows VALUES('transcripts',%s,%s)",(91000+i,Jsonb({'id':i,'raw_doc_id':100+i,'ticker':'ABC','fiscal_year':2026,'fiscal_period':'Q1'})))
            pg.execute("INSERT INTO snapshot_metadata(singleton,snapshot_at,source_observed_at,document_count,list_row_count,generation_id) VALUES(true,'fixture',now(),1,1,'00000000-0000-0000-0000-000000000001') ON CONFLICT(singleton) DO NOTHING")
        with self.target() as pg:
            fork_chat_preview(self.source,pg,self.fixture.schema);import_questions(self.q,pg)
            pg.execute("UPDATE question_capture_rows SET row_data=jsonb_set(row_data,'{tickers}',to_jsonb('ABC'::text)) WHERE table_name='proxy_registry' AND row_data->>'id'='3'")
        calls=[]
        def model(prompt,**kw):
            calls.append(kw['task'])
            return SimpleNamespace(text='{"found":true,"value_num":12,"value_text":"12","direction":"up"}' if len(calls)==1 else '{"found":false}')
        result=extract_numeric(self.target,1,run_llm=model)
        self.assertEqual(result,{'extracted':1,'scanned':2,'stale':0,'graph_projection_required':True})
        self.assertEqual(extract_numeric(self.target,1,run_llm=model)['scanned'],0)
        self.assertEqual(len(calls),2)
        detail=QuestionsFixture(self.target).proxy(3)
        self.assertEqual(len(detail['observations']),2)
        self.assertTrue(any(o['value_num']==12 for o in detail['observations']))

    def test_numeric_discards_changed_transcript_during_model_call(self):
        from types import SimpleNamespace
        from psycopg.types.json import Jsonb
        from pipeline.postgres_question_numeric_fixture import extract_numeric
        with self.fixture.pg() as pg:
            for table in ('raw_documents','transcripts'):
                pg.execute('INSERT INTO legacy_snapshot_tables VALUES(%s,%s,%s,1) ON CONFLICT DO NOTHING',(table,Jsonb([]),'fixture'))
            pg.execute("INSERT INTO legacy_snapshot_rows VALUES('raw_documents',91001,%s)",(Jsonb({'id':109,'markdown':'원래 본문'}),))
            pg.execute("INSERT INTO legacy_snapshot_rows VALUES('transcripts',91001,%s)",(Jsonb({'id':9,'raw_doc_id':109,'ticker':'ABC','fiscal_year':2026,'fiscal_period':'Q1'}),))
            pg.execute("INSERT INTO snapshot_metadata(singleton,snapshot_at,source_observed_at,document_count,list_row_count,generation_id) VALUES(true,'fixture',now(),1,1,'00000000-0000-0000-0000-000000000001') ON CONFLICT(singleton) DO NOTHING")
        with self.target() as pg:
            fork_chat_preview(self.source,pg,self.fixture.schema);import_questions(self.q,pg)
            pg.execute("UPDATE question_capture_rows SET row_data=jsonb_set(row_data,'{tickers}',to_jsonb('ABC'::text)) WHERE table_name='proxy_registry' AND row_data->>'id'='3'")
        def model(prompt,**kw):
            with self.fixture.pg() as pg:
                pg.execute("UPDATE legacy_snapshot_rows SET row_data=jsonb_set(row_data,'{markdown}',to_jsonb('변경 본문'::text)) WHERE table_name='raw_documents' AND row_ordinal=91001")
            return SimpleNamespace(text='{"found":true,"value_num":12}')
        result=extract_numeric(self.target,1,run_llm=model)
        self.assertEqual(result['stale'],1)
        self.assertEqual(result['extracted'],0)
        self.assertEqual(len(QuestionsFixture(self.target).proxy(3)['observations']),1)

    def test_entity_observation_projection_is_idempotent(self):
        from pipeline.postgres_question_numeric_fixture import project_numeric_observations,entity_observations
        with self.target() as pg:import_questions(self.q,pg)
        self.assertEqual(project_numeric_observations(self.target),{'projected':1})
        rows=entity_observations(self.target,42)
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['metric'],rows[0]['value'],rows[0]['source']),('q1_signal_0',1,'proxy:transcript'))
        self.assertEqual(project_numeric_observations(self.target),{'projected':0})
        self.assertEqual(len(entity_observations(self.target,42)),1)

    def test_rollup_matches_original_rules_and_persists(self):
        from types import SimpleNamespace
        from pipeline.postgres_question_rollup_fixture import rollup_question
        self.q.rollback();self.q.execute('PRAGMA query_only=OFF')
        self.q.execute('UPDATE questions SET narrative_id=NULL WHERE id=1')
        self.q.commit();self.q.execute('PRAGMA query_only=ON');self.q.execute('BEGIN')
        with self.target() as pg:import_questions(self.q,pg)
        result=rollup_question(self.target,1,run_llm=lambda *a,**k:SimpleNamespace(text='관측이 긍정적입니다.'))
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['confirm_verdict'],'leaning_yes')
        tree=QuestionsFixture(self.target).detail(1)
        self.assertEqual(tree['confirm_verdict'],'leaning_yes')
        self.assertEqual(tree['sub_questions'][0]['verdict'],'leaning_yes')
        self.assertEqual(tree['verdict_summary'],'관측이 긍정적입니다.')

    def test_rollup_refuses_unwired_shared_graph_update(self):
        from types import SimpleNamespace
        from pipeline.postgres_question_rollup_fixture import rollup_question
        with self.target() as pg:import_questions(self.q,pg)
        with self.assertRaises(NotImplementedError):
            rollup_question(self.target,1,run_llm=lambda *a,**k:SimpleNamespace(text='요약'))
        self.assertEqual(QuestionsFixture(self.target).detail(1)['confirm_verdict'],'unknown')

    def test_rollup_discards_result_when_inputs_change(self):
        from types import SimpleNamespace
        from pipeline.postgres_question_rollup_fixture import rollup_question
        self.q.rollback();self.q.execute('PRAGMA query_only=OFF')
        self.q.execute('UPDATE questions SET narrative_id=NULL WHERE id=1')
        self.q.commit();self.q.execute('PRAGMA query_only=ON');self.q.execute('BEGIN')
        with self.target() as pg:import_questions(self.q,pg)
        def model(prompt,**kwargs):
            with self.target() as pg:
                pg.execute("UPDATE question_capture_rows SET row_data=jsonb_set(row_data,'{direction}',to_jsonb('down'::text)) WHERE table_name='proxy_observations' AND row_data->>'id'='5'")
            return SimpleNamespace(text='오래된 요약')
        self.assertEqual(rollup_question(self.target,1,run_llm=model),{'status':'stale'})
        tree=QuestionsFixture(self.target).detail(1)
        self.assertEqual(tree['confirm_verdict'],'unknown')

    def test_graph_confirmation_updates_all_candidate_read_paths_atomically(self):
        from types import SimpleNamespace
        from psycopg.types.json import Jsonb
        from pipeline.postgres_question_rollup_fixture import rollup_question
        edge={'id':1,'narrative_id':7,'promoted_knowledge_id':9,'obs_confirmed_at':None,'obs_confirmed_qid':None}
        evidence={'id':15,'narrative_id':7,'entity_relation_id':1}
        with self.fixture.pg() as pg:
            import_questions(self.q,pg)
            for name in ('entity_relations','narrative_edge_evidence'):
                pg.execute('INSERT INTO legacy_snapshot_tables VALUES(%s,%s,%s,1) ON CONFLICT DO NOTHING',(name,Jsonb([]),'fixture'))
            pg.execute("INSERT INTO legacy_snapshot_rows VALUES('entity_relations',91001,%s)",(Jsonb(edge),))
            pg.execute("INSERT INTO legacy_snapshot_rows VALUES('narrative_edge_evidence',91001,%s)",(Jsonb(evidence),))
            pg.execute('INSERT INTO ingest_graph_state DEFAULT VALUES ON CONFLICT DO NOTHING')
            pg.execute('INSERT INTO ingest_narrative_ledger_state DEFAULT VALUES ON CONFLICT DO NOTHING')
            pg.execute("INSERT INTO ingest_graph_relations(id,src_id,dst_id,rel_type,source_row) OVERRIDING SYSTEM VALUE VALUES(1,1,2,'fixture',%s)",(Jsonb(edge),))
            pg.execute('INSERT INTO ingest_narrative_evidence(id,source_row) OVERRIDING SYSTEM VALUE VALUES(15,%s)',(Jsonb(evidence),))
        result=rollup_question(self.fixture.pg,1,run_llm=lambda *a,**k:SimpleNamespace(text='요약'))
        self.assertEqual(result['status'],'ok');self.assertEqual(result['edges_confirmed'],1)
        with self.fixture.pg() as pg:
            a=pg.execute("SELECT row_data FROM question_capture_rows WHERE table_name='entity_relations' AND row_data->>'id'='1'").fetchone()[0]
            b=pg.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entity_relations' AND row_data->>'id'='1'").fetchone()[0]
            c=pg.execute('SELECT source_row FROM ingest_graph_relations WHERE id=1').fetchone()[0]
            self.assertEqual(a,b);self.assertEqual(b,c)
            self.assertEqual(a['obs_confirmed_qid'],1);self.assertIsNotNone(a['obs_confirmed_at'])
        self.assertEqual(QuestionsFixture(self.fixture.pg).detail(1)['confirm_verdict'],'leaning_yes')

    def test_graph_confirmation_refuses_diverged_graph_without_partial_write(self):
        from types import SimpleNamespace
        from psycopg.types.json import Jsonb
        from pipeline.postgres_question_rollup_fixture import rollup_question
        edge={'id':1,'narrative_id':7,'promoted_knowledge_id':9,'obs_confirmed_at':None,'obs_confirmed_qid':None}
        evidence={'id':15,'narrative_id':7,'entity_relation_id':1}
        with self.fixture.pg() as pg:
            import_questions(self.q,pg)
            for name in ('entity_relations','narrative_edge_evidence'):
                pg.execute('INSERT INTO legacy_snapshot_tables VALUES(%s,%s,%s,1) ON CONFLICT DO NOTHING',(name,Jsonb([]),'fixture'))
            pg.execute("INSERT INTO legacy_snapshot_rows VALUES('entity_relations',91002,%s)",(Jsonb(edge),))
            pg.execute("INSERT INTO legacy_snapshot_rows VALUES('narrative_edge_evidence',91002,%s)",(Jsonb(evidence),))
            pg.execute('INSERT INTO ingest_graph_state DEFAULT VALUES ON CONFLICT DO NOTHING')
            pg.execute('INSERT INTO ingest_narrative_ledger_state DEFAULT VALUES ON CONFLICT DO NOTHING')
            pg.execute("INSERT INTO ingest_graph_relations(id,src_id,dst_id,rel_type,source_row) OVERRIDING SYSTEM VALUE VALUES(1,1,2,'fixture',%s)",(Jsonb({**edge,'promoted_knowledge_id':99}),))
            pg.execute('INSERT INTO ingest_narrative_evidence(id,source_row) OVERRIDING SYSTEM VALUE VALUES(15,%s)',(Jsonb(evidence),))
        result=rollup_question(self.fixture.pg,1,run_llm=lambda *a,**k:SimpleNamespace(text='요약'))
        self.assertEqual(result,{'status':'stale'})
        self.assertEqual(QuestionsFixture(self.fixture.pg).detail(1)['confirm_verdict'],'unknown')
        with self.fixture.pg() as pg:
            row=pg.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entity_relations' AND row_data->>'id'='1'").fetchone()[0]
            self.assertIsNone(row['obs_confirmed_at'])

    def test_small_graph_overlay_updates_candidate_without_mutating_base(self):
        from types import SimpleNamespace
        from psycopg.types.json import Jsonb
        from pipeline.postgres_question_graph_overlay import install_graph_overlay
        from pipeline.postgres_question_rollup_fixture import rollup_question
        edge={'id':1,'narrative_id':7,'promoted_knowledge_id':9,'obs_confirmed_at':None,'obs_confirmed_qid':None}
        evidence={'id':15,'narrative_id':7,'entity_relation_id':1}
        with self.fixture.pg() as pg:
            for name,row in (('entity_relations',edge),('narrative_edge_evidence',evidence)):
                pg.execute('INSERT INTO legacy_snapshot_tables VALUES(%s,%s,%s,0) ON CONFLICT DO NOTHING',(name,Jsonb([]),'fixture'))
                pg.execute('INSERT INTO legacy_snapshot_rows VALUES(%s,92001,%s)',(name,Jsonb(row)))
                pg.execute('UPDATE legacy_snapshot_tables SET row_count=(SELECT count(*) FROM legacy_snapshot_rows WHERE table_name=%s) WHERE table_name=%s',(name,name))
        with self.target() as pg:
            fork_chat_preview(self.source,pg,self.fixture.schema)
            copied=install_graph_overlay(pg,self.fixture.schema)
            self.assertGreaterEqual(copied['relations'],1)
            import_questions(self.q,pg)
        result=rollup_question(self.target,1,run_llm=lambda *a,**k:SimpleNamespace(text='요약'))
        self.assertEqual(result['status'],'ok');self.assertEqual(result['edges_confirmed'],1)
        with self.target() as pg:
            read=pg.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entity_relations' AND row_data->>'id'='1'").fetchone()[0]
            ledger=pg.execute('SELECT source_row FROM question_graph_overlay_relations WHERE id=1').fetchone()[0]
            self.assertEqual(read,ledger);self.assertEqual(read['obs_confirmed_qid'],1)
        with self.fixture.pg() as pg:
            base=pg.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entity_relations' AND row_data->>'id'='1'").fetchone()[0]
            self.assertIsNone(base['obs_confirmed_qid'])
