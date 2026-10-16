"""Deterministic chat attachment contract (stored documents attached to a conversation)."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipeline import expectation_reading as reading, expectation_evidence as evidence
from pipeline import chat, chat_memory
from routers import spine_ask

class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.corpus = Path(self.tmp.name) / 'corpus.sqlite'
        with closing(sqlite3.connect(self.corpus)) as c, c:
            c.execute('''CREATE TABLE raw_documents (id INTEGER PRIMARY KEY, source_type TEXT,
                         source_id TEXT,title TEXT,url TEXT,published_at TEXT,fetched_at TEXT,
                         raw_content TEXT,markdown TEXT,digest_status TEXT)''')
            for i in range(1,8):
                body=f'안녕하세요. 연구자입니다. 2027년 DRAM 계약가 상승률을 {i*10}%로 전망합니다.'
                c.execute('INSERT INTO raw_documents VALUES (?,?,?,?,?,?,?,?,?,?)',
                          (i,'telegram','channel',f'DRAM 전망 {i}','https://example.test/report',
                           f'2026-08-{i:02}T10:00:00+09:00','2026-09-01T00:00:00Z',body,body,None))
            body='HBM 원본 자막 3,000자 → opus 정리본'
            c.execute('INSERT INTO raw_documents VALUES (?,?,?,?,?,?,?,?,?,?)',
                      (8,'youtube','channel','정리본',None,None,None,body,body,'ok'))
        self.original = self.corpus.read_bytes()
        p=patch.object(evidence,'DB_PATH',self.corpus);p.start();self.addCleanup(p.stop)
        self.client=TestClient(FastAPI())
        self.addCleanup(self.client.close)
        self.addCleanup(self.tmp.cleanup)

    def test_attached_body_is_read_without_summary_promotion(self):
        items=reading.attached_evidence([3,8,3,999])
        self.assertEqual([i['doc_id'] for i in items],[3,8])
        self.assertIn('직접 발언 인용 금지',items[1]['text'])
        self.assertIn(evidence.get_document(3).text,items[0]['text'])
        self.assertEqual(self.original,self.corpus.read_bytes())

    def test_attachments_precede_search_are_not_duplicated_and_persist_across_turn(self):
        ctx={'state':{'attached_doc_ids':[2,1]},'recent':[],'related':[]}
        def route(turn,status): turn.calls=[{'name':'search_docs','args':{}}]
        tool=SimpleNamespace(name='search_docs',args={},items=[{'kind':'doc','doc_id':2,'title':'duplicate','text':'bad'},
                                                               {'kind':'doc','doc_id':4,'title':'new','text':'extra'}],note=None,assumed=[])
        with patch.object(chat,'_route',side_effect=route), patch.object(chat,'run_tool',return_value=tool), \
             patch.object(chat,'_review'),patch.object(chat,'_synthesize'),patch.object(chat,'_verify'):
            first=chat.run_turn('비교해줘',ctx=ctx)
            second=chat.run_turn('그럼 그 사람은 왜 걱정해?',ctx=ctx)
        self.assertEqual([i['doc_id'] for i in first.evidence],[2,1,4])
        self.assertEqual([i['doc_id'] for i in second.evidence],[2,1,4])
        self.assertIn('첨부 자료 제목',chat._router_user(first))

    def test_long_video_keeps_memory_passage_in_the_middle(self):
        text='도입부. '+('가나다 ' * 2000)+' HBM 수요는 늘지만 현금 비중은 줄인다. '+('끝부분 ' * 2000)
        excerpt=reading._attachment_excerpt(text)
        self.assertIn('HBM 수요는 늘지만 현금 비중은 줄인다.',excerpt)
        self.assertTrue(excerpt.startswith('도입부.'))
        self.assertLess(len(excerpt),7100)
        self.assertIn('중간 본문 생략',excerpt)

    def test_attached_body_reuse_is_not_a_failed_lookup(self):
        turn=chat.Turn(question='비교해줘',conversation_id=None,ctx={})
        turn.evidence=reading.attached_evidence([1])
        turn.calls=[{'name':'open_doc','args':{'doc_id':1}}]
        turn.route={'intent':'synthesis','answer_style':'analysis'}
        with patch.object(chat,'run_tool') as run:
            chat._gather(turn,lambda _:None)
            run.assert_not_called()
        self.assertEqual(turn.tool_log[-1]['n'],1)
        self.assertFalse(chat._needs_review(turn))
        turn.calls.append({'name':'get_quote','args':{'entity':'삼성전자'}})
        self.assertTrue(chat._needs_review(turn))

    def test_attachment_state_preserves_existing_notes_and_can_clear(self):
        with closing(sqlite3.connect(self.corpus)) as c, c:
            c.execute('CREATE TABLE conversations(id INTEGER PRIMARY KEY,state_json TEXT)')
            c.execute('INSERT INTO conversations VALUES (1, ?)', ('{"note_upto":9}',))
        def conn():
            c=sqlite3.connect(self.corpus);c.row_factory=sqlite3.Row;return c
        with patch.object(chat_memory,'get_connection',side_effect=conn):
            chat_memory.set_attached_documents(1,[2,1])
            with closing(conn()) as c:
                import json
                state=json.loads(c.execute('SELECT state_json FROM conversations').fetchone()[0])
                self.assertEqual(state,{'note_upto':9,'attached_doc_ids':[2,1]})
            chat_memory.set_attached_documents(1,[])
            with closing(conn()) as c:
                self.assertEqual(json.loads(c.execute('SELECT state_json FROM conversations').fetchone()[0])['attached_doc_ids'],[])

    def test_ask_validates_documents_before_creating_conversation(self):
        self.client.app.include_router(spine_ask.router)
        with patch('pipeline.conversations.log_question',return_value=99) as log, \
             patch.object(chat_memory,'set_attached_documents') as save, \
             patch.object(spine_ask,'_generate_answer'):
            self.assertEqual(self.client.post('/api/spine/ask',json={'question':'읽어줘','document_ids':[999]}).status_code,422)
            log.assert_not_called()
            response=self.client.post('/api/spine/ask',json={'question':'읽어줘','document_ids':[2,1,2]})
            self.assertEqual(response.status_code,200,response.text)
            save.assert_called_once_with(99,[2,1])
            self.assertEqual(self.client.post('/api/spine/ask',json={'question':'읽어줘','document_ids':list(range(1,15))}).status_code,422)

if __name__=='__main__': unittest.main()
