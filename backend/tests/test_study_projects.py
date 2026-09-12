import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from pipeline import study, study_projects as projects
from routers.spine_study import Annotation, EditAnnotation
from routers.spine_study_projects import Question, Source, Edit, Clip

class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
        self.patches=[patch.object(m,'get_connection',side_effect=self.connect) for m in (study,projects)]
        for p in self.patches:p.start()
        c=self.connect();c.executescript(study.SCHEMA+projects.SCHEMA+'''
        CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,title TEXT,url TEXT,source_type TEXT,published_at TEXT,markdown TEXT,raw_content TEXT);
        CREATE TABLE conversations(id INTEGER PRIMARY KEY,channel TEXT,title TEXT,state_json TEXT,updated_at TEXT);
        CREATE TABLE chat_messages(id INTEGER PRIMARY KEY,conversation_id INTEGER,role TEXT,content TEXT);
        CREATE TABLE saved_items(id INTEGER PRIMARY KEY,ref_id TEXT);
        INSERT INTO saved_items VALUES(1,'1');
        INSERT INTO raw_documents VALUES(1,'인터뷰','https://example.com/one','youtube','2026-09-01',NULL,'가😀나다. 공급 부족을 걱정한다.');
        INSERT INTO raw_documents VALUES(2,'오늘의 컨콜','https://example.com/two','transcript','2026-09-11',NULL,'오늘은 재고 증가가 걱정이다.');
        ''');c.commit();c.close();self.pid=projects.create('HBM 기대 변화')['id']
    def tearDown(self):
        for p in self.patches:p.stop()
        self.tmp.cleanup()
    def connect(self):
        c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
    def add(self):return projects.add_documents(self.pid,[1,2])['study_ids']
    def question(self,sids,key='request-0001',annotations=None):
        return Question(question='두 시점의 기대는 왜 다른가?',sources=[Source(study_id=sid,annotations=annotations if i==0 and annotations else []) for i,sid in enumerate(sids)],request_key=key)
    def test_bookmarks_and_other_project_annotations_are_independent(self):
        original=study.open_document(1)['id'];first=self.add()[0];other=projects.create('다른 관점')['id'];second=projects.add_documents(other,[1])['study_ids'][0]
        self.assertEqual(len({original,first,second}),3)
        study.add_annotation(first,Annotation(kind='comment',start=1,end=3,exact='😀나',comment='왜?'))
        self.assertEqual(len(study.read_study(first)['annotations']),1)
        self.assertEqual(study.read_study(second)['annotations'],[])
        projects.remove(self.pid,first)
        self.assertEqual(projects.add_documents(self.pid,[1])['study_ids'],[first])
        c=self.connect();self.assertEqual(c.execute('SELECT count(*) FROM saved_items').fetchone()[0],1);c.close()
        self.assertEqual([s['id'] for s in study.list_studies()],[original])
    def test_context_scopes_dates_comments_and_history_are_fixed(self):
        sids=self.add();a=study.add_annotation(sids[0],Annotation(kind='comment',start=1,end=3,exact='😀나',comment='내 질문'))
        body=self.question(sids,annotations=[{'id':a['id'],'revision':1}]);turn=projects.queue_turn(self.pid,body)
        study.edit_annotation(sids[0],a['id'],EditAnnotation(revision=1,comment='나중 생각'))
        projects.remove(self.pid,sids[0]);context=projects.read(self.pid)['turns'][0]['context']
        self.assertEqual(context['sources'][0]['annotations'][0]['comment'],'내 질문')
        self.assertIn('2026-09-01',context['evidence'][0]['text'])
        self.assertIn('2026-09-11',context['evidence'][1]['text'])
        self.assertIn('/study/projects/',context['evidence'][0]['href'])
        again=projects.queue_turn(self.pid,body);self.assertEqual(turn['id'],again['id']);self.assertFalse(again['created'])
        with self.assertRaises(HTTPException):projects.queue_turn(self.pid,self.question([sids[1]],'different-key'))
    def test_foreign_removed_and_stale_annotation_rejected(self):
        sids=self.add();other=projects.create('other')['id'];sid=projects.add_documents(other,[1])['study_ids'][0]
        with self.assertRaises(HTTPException):projects.queue_turn(self.pid,self.question([sid]))
        a=study.add_annotation(sids[0],Annotation(kind='highlight',start=0,end=1,exact='가'))
        with self.assertRaises(HTTPException):projects.queue_turn(self.pid,self.question(sids,annotations=[{'id':a['id'],'revision':99}]))
        projects.remove(self.pid,sids[0])
        with self.assertRaises(HTTPException):projects.queue_turn(self.pid,self.question(sids))
    def test_note_revision_and_paste_do_not_write_raw_or_bookmarks(self):
        projects.edit(self.pid,Edit(title='이름 수정',note='내 결론',revision=1))
        with self.assertRaises(HTTPException):projects.edit(self.pid,Edit(title='충돌',note='덮기',revision=1))
        sid=projects.add_clip(self.pid,Clip(title='내 메모',text='기대의 기울기가 달라졌다.',url='https://example.com'))['study_ids'][0]
        self.assertIsNone(study.read_study(sid)['document_id'])
        c=self.connect();self.assertEqual(c.execute('SELECT count(*) FROM raw_documents').fetchone()[0],2);c.close()
    def test_migration_preserves_existing_ids_body_annotations_turns(self):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
        old=study.SCHEMA.replace('document_id INTEGER, project_id INTEGER NOT NULL DEFAULT 0','document_id INTEGER NOT NULL UNIQUE').replace(",\n UNIQUE(document_id, project_id)","")
        c.executescript(old)
        c.execute("INSERT INTO study_sessions(id,document_id,title,body_kind,body,content_hash) VALUES(7,42,'old','original','가😀나','hash')")
        c.execute("INSERT INTO study_annotations(id,study_id,kind,start_offset,end_offset,exact) VALUES(8,7,'highlight',1,2,'😀')")
        c.execute("INSERT INTO study_turns(id,study_id,conversation_id,message_id,request_key,question,context_json) VALUES(9,7,1,2,'old-request','왜?','{}')");c.commit()
        projects.migrate(c);projects.migrate(c)
        self.assertEqual(c.execute('SELECT body FROM study_sessions WHERE id=7').fetchone()[0],'가😀나')
        self.assertEqual(c.execute('SELECT exact FROM study_annotations WHERE id=8').fetchone()[0],'😀')
        self.assertEqual(c.execute('SELECT study_id FROM study_turns WHERE id=9').fetchone()[0],7)
        self.assertEqual(list(c.execute('PRAGMA foreign_key_check')),[])
        c.execute("INSERT INTO study_sessions(document_id,project_id,title,body_kind,body,content_hash) VALUES(42,1,'new','original','text','hash')")
        c.close()
    def test_execution_uses_existing_chat_with_multi_source_context(self):
        tid=projects.queue_turn(self.pid,self.question(self.add()))['id']
        with patch('pipeline.chat.generate_answer',return_value={}) as generate:
            projects.execute_turn(tid)
            self.assertEqual(len(generate.call_args.kwargs['study_context']['sources']),2)
        self.assertEqual(projects.read(self.pid)['turns'][0]['status'],'complete')
    def test_recovery_is_time_gated(self):
        tid=projects.queue_turn(self.pid,self.question(self.add()))['id']
        with self.assertRaises(HTTPException):projects.recover(self.pid,tid)
        c=self.connect();c.execute("UPDATE study_project_turns SET created_at=datetime('now','-11 minutes')");c.commit();c.close()
        projects.recover(self.pid,tid)
        self.assertEqual(projects.read(self.pid)['turns'][0]['status'],'error')
    def test_search_matches_url_without_wildcard_injection(self):
        self.assertEqual(len(projects.search('example.com/one')),1)
        self.assertEqual(projects.search('%'),[])

    def test_invalid_batch_has_no_partial_members_or_snapshots(self):
        with self.assertRaises(HTTPException):projects.add_documents(self.pid,[1,99999])
        self.assertEqual(projects.read(self.pid)['documents'],[])
        c=self.connect();self.assertEqual(c.execute('SELECT count(*) FROM study_sessions WHERE project_id=?',(self.pid,)).fetchone()[0],0);c.close()
    def test_context_budget_rejects_instead_of_silently_dropping_sources(self):
        ids=[projects.add_clip(self.pid,Clip(title=str(i),text='본문' * 9000))['study_ids'][0] for i in range(6)]
        with self.assertRaises(HTTPException) as err:projects.queue_turn(self.pid,self.question(ids))
        self.assertEqual(err.exception.status_code,422)
        self.assertEqual(projects.read(self.pid)['turns'],[])
