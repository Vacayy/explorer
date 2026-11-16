"""Question capture reads only from its disposable PG snapshot."""
import sqlite3
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipeline.postgres_questions_fixture import import_questions,QuestionsFixture
from routers.postgres_questions_fixture import create_router
from tests.test_postgres_chat_preview_fork import ChatPreviewForkTests


class QuestionsFixtureTests(ChatPreviewForkTests):
    def setUp(self):
        super().setUp()
        self.q=sqlite3.connect(':memory:');self.addCleanup(self.q.close)
        self.q.executescript('''
        CREATE TABLE questions(id INTEGER PRIMARY KEY AUTOINCREMENT,text TEXT,narrative_id INTEGER,source_doc_id INTEGER,status TEXT,updated_at TEXT,lead_verdict TEXT,confirm_verdict TEXT,divergence TEXT,last_viewed_at TEXT);
        CREATE TABLE sub_questions(id INTEGER PRIMARY KEY,question_id INTEGER,text TEXT,verdict TEXT);
        CREATE TABLE proxy_registry(id INTEGER PRIMARY KEY,sub_question_id INTEGER,label TEXT,modality TEXT,yes_direction TEXT,unit TEXT,tickers TEXT,extract_hint TEXT,active INTEGER);
        CREATE TABLE proxy_observations(id INTEGER PRIMARY KEY,proxy_id INTEGER,transcript_id INTEGER,observed_at TEXT,value_num REAL,value_text TEXT,direction TEXT,confidence REAL,source_type TEXT);
        CREATE TABLE question_reports(id INTEGER PRIMARY KEY,question_id INTEGER,body TEXT,inputs_hash TEXT,created_at TEXT);
        CREATE TABLE proxy_scans(proxy_id INTEGER,transcript_id INTEGER);
        CREATE TABLE scenarios(topic TEXT,event TEXT,answer TEXT,beneficiaries TEXT,created_at TEXT,question_id INTEGER);
        CREATE TABLE transcripts(id INTEGER PRIMARY KEY,raw_doc_id INTEGER,ticker TEXT,fiscal_year INTEGER,fiscal_period TEXT);
        CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,title TEXT,source_type TEXT);
        INSERT INTO questions VALUES(1,'원래 질문',7,10,'active','2026-01-01','unknown','unknown',NULL,NULL);
        INSERT INTO sub_questions VALUES(2,1,'하위 질문','unknown');
        INSERT INTO proxy_registry VALUES(3,2,'관측','numeric','up','개',NULL,NULL,1);
        INSERT INTO transcripts VALUES(4,10,'ABC',2026,'Q1');
        INSERT INTO proxy_observations VALUES(5,3,4,'2026-01-01',1,NULL,'up',0.8,'transcript');
        INSERT INTO raw_documents VALUES(10,'자료','transcript');
        INSERT INTO scenarios VALUES('주제','사건','답변','[]','2026-01-01',1);
        CREATE TABLE entity_relations(id INTEGER PRIMARY KEY,narrative_id INTEGER,promoted_knowledge_id INTEGER);
        CREATE TABLE knowledge(id INTEGER PRIMARY KEY,statement TEXT,epistemic_status TEXT);
        CREATE TABLE knowledge_falsifiers(id INTEGER PRIMARY KEY,knowledge_id INTEGER,condition TEXT,triggered_at TEXT);
        INSERT INTO entity_relations VALUES(1,7,9);
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
