import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from pipeline import study, chat
from routers.spine_study import Annotation, EditAnnotation, StudyQuestion, AnnotationRef

class StudyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.db'
        self.mock=patch.object(study,'get_connection',side_effect=self.connect);self.mock.start()
        c=self.connect();c.executescript(study.SCHEMA+'''
        CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,title TEXT,url TEXT,source_type TEXT,published_at TEXT,markdown TEXT,raw_content TEXT);
        CREATE TABLE conversations(id INTEGER PRIMARY KEY,channel TEXT,title TEXT,state_json TEXT,updated_at TEXT);
        CREATE TABLE chat_messages(id INTEGER PRIMARY KEY,conversation_id INTEGER,role TEXT,content TEXT);
        INSERT INTO raw_documents VALUES(1,'공부할 글','https://example.com/1','blog','2026-09-10',NULL,'가😀나다. 다음 문장.');
        INSERT INTO raw_documents VALUES(2,'다른 글','https://example.com/2','telegram','2026-09-10',NULL,'다른 내용');
        ''');c.commit();c.close();self.sid=study.open_document(1)['id']
    def tearDown(self):self.mock.stop();self.tmp.cleanup()
    def connect(self):
        c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;return c
    def mark(self):return study.add_annotation(self.sid,Annotation(kind='highlight',start=1,end=3,exact='😀나',comment='왜 그럴까?'))
    def question(self,a,key='test-key-1'):
        return StudyQuestion(research='off',question='이해를 도와줘',annotations=[AnnotationRef(id=a['id'],revision=a['revision'])],request_key=key)
    def test_snapshot_survives_source_change_and_reopening(self):
        c=self.connect();c.execute("UPDATE raw_documents SET raw_content='바뀐 내용' WHERE id=1");c.commit();c.close()
        self.assertEqual(study.open_document(1)['id'],self.sid)
        self.assertEqual(study.read_study(self.sid)['body'],'가😀나다. 다음 문장.')
    def test_unicode_exact_anchor_and_revision_conflict(self):
        a=self.mark();self.assertEqual(a['exact'],'😀나')
        with self.assertRaises(HTTPException):study.add_annotation(self.sid,Annotation(kind='highlight',start=1,end=2,exact='틀림'))
        study.edit_annotation(self.sid,a['id'],EditAnnotation(revision=1,comment='새 생각'))
        with self.assertRaises(HTTPException) as err:study.edit_annotation(self.sid,a['id'],EditAnnotation(revision=1,comment='덮어쓰기'))
        self.assertEqual(err.exception.status_code,409)
    def test_context_is_immutable_with_quote_comment_and_no_unselected_notes(self):
        a=self.mark();other=study.add_annotation(self.sid,Annotation(kind='comment',start=6,end=8,exact='다음',comment='포함하지 않을 생각'))
        result=study.queue_turn(self.sid,self.question(a));self.assertTrue(result['created'])
        study.edit_annotation(self.sid,a['id'],EditAnnotation(revision=1,comment='나중에 바뀐 생각'))
        t=study.read_study(self.sid)['turns'][0]['context'];self.assertEqual(t['annotations'][0]['comment'],'왜 그럴까?')
        self.assertNotIn('포함하지 않을 생각',json.dumps(t,ensure_ascii=False))
        self.assertIn('😀나',t['evidence'][0]['text']);self.assertIn('왜 그럴까?',t['evidence'][0]['text'])
    def test_duplicate_admission_and_parallel_turn_are_safe(self):
        a=self.mark();first=study.queue_turn(self.sid,self.question(a));again=study.queue_turn(self.sid,self.question(a))
        self.assertEqual(first['id'],again['id']);self.assertFalse(again['created'])
        with self.assertRaises(HTTPException):study.queue_turn(self.sid,self.question(a,'test-key-2'))
        c=self.connect();self.assertEqual(c.execute('SELECT count(*) FROM chat_messages').fetchone()[0],1);c.close()
    def test_foreign_and_deleted_annotations_are_rejected(self):
        a=self.mark();second=study.open_document(2)['id']
        with self.assertRaises(HTTPException):study.queue_turn(second,self.question(a))
        study.edit_annotation(self.sid,a['id'],EditAnnotation(revision=1,delete=True))
        with self.assertRaises(HTTPException):study.queue_turn(self.sid,self.question(a))
    def test_study_engine_uses_context_and_never_runs_search_router(self):
        a=self.mark();r=study.queue_turn(self.sid,self.question(a));context=study.read_study(self.sid)['turns'][0]['context']
        with patch.object(chat,'_route') as route,patch.object(chat,'_gather') as gather,patch.object(chat,'_review') as review,patch.object(chat,'_synthesize') as synth,patch.object(chat,'_verify'):
            turn=chat.run_turn('이해를 도와줘',conversation_id=r['conversation_id'],ctx={'state':{}},study_context=context)
            route.assert_not_called();gather.assert_not_called();review.assert_not_called();synth.assert_called_once()
        self.assertEqual(turn.evidence,context['evidence'])
        self.assertEqual(turn.route['intent'],'study')

    def test_stalled_recovery_waits_and_closes_pending_history(self):
        a=self.mark();r=study.queue_turn(self.sid,self.question(a))
        with self.assertRaises(HTTPException):study.recover_turn(self.sid,r['id'])
        c=self.connect();c.execute("UPDATE study_turns SET created_at=datetime('now','-11 minutes') WHERE id=?",(r['id'],));c.commit();c.close()
        study.recover_turn(self.sid,r['id'])
        self.assertEqual(study.read_study(self.sid)['turns'][0]['status'],'error')
        c=self.connect();self.assertEqual(c.execute('SELECT role FROM chat_messages ORDER BY id DESC LIMIT 1').fetchone()[0],'assistant');c.close()
        self.assertTrue(study.queue_turn(self.sid,self.question(a,'next-key-1'))['created'])

    def test_summary_rejects_comments_and_empty_questions(self):
        a=study.add_annotation(self.sid,Annotation(kind='comment',start=0,end=1,exact='가',comment='질문'))
        body=self.question(a);body.action='summarize'
        with self.assertRaises(HTTPException):study.queue_turn(self.sid,body)
        body.action='question';body.question=' '
        with self.assertRaises(HTTPException):study.queue_turn(self.sid,body)

    def test_deleted_quote_remains_in_historical_context(self):
        a=self.mark();study.queue_turn(self.sid,self.question(a))
        study.edit_annotation(self.sid,a['id'],EditAnnotation(revision=1,delete=True))
        s=study.read_study(self.sid)
        self.assertEqual(s['annotations'],[])
        self.assertEqual(s['turns'][0]['context']['annotations'][0]['exact'],'😀나')
