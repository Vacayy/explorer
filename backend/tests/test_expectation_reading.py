"""Reading surface and deterministic chat attachment contract."""
from contextlib import closing
from datetime import datetime, timezone
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import test_expectation_workflow as workflow_tests
BASE = workflow_tests.BASE
from pipeline import expectation_reading as reading, expectation_evidence as evidence
from pipeline import chat, chat_memory
from routers import spine_ask

class ReadingTests(unittest.TestCase):
    setUp = workflow_tests.WorkflowTests.setUp

    def test_period_publication_order_filters_and_read_only(self):
        result=reading.reading(days=7,now=datetime(2026,8,8,tzinfo=timezone.utc))
        self.assertEqual([i.document.id for i in result.items],[7,6,5,4,3,2,1])
        self.assertEqual(result.matched,7)
        self.assertEqual(result.source_counts,{'telegram':7})
        self.assertEqual(reading.reading(days=7,product='hbm',now=datetime(2026,8,8,tzinfo=timezone.utc)).items,[])
        self.assertEqual(self.original,self.corpus.read_bytes())

    def test_same_body_groups_and_balanced_platform_attachments(self):
        with closing(sqlite3.connect(self.corpus)) as c, c:
            c.execute("UPDATE raw_documents SET source_type='youtube' WHERE id=6")
            c.execute("UPDATE raw_documents SET source_type='blog' WHERE id=5")
            body=evidence.get_document(7).text
            c.execute('UPDATE raw_documents SET markdown=?,raw_content=? WHERE id=4',(body,body))
        result=reading.reading(days=7,now=datetime(2026,8,8,tzinfo=timezone.utc))
        self.assertEqual(result.duplicates,1)
        self.assertEqual(result.items[0].copies,[4])
        self.assertTrue({5,6,7}.issubset(result.discussion_ids))
        self.assertNotIn(4,result.discussion_ids)

    def test_history_stays_in_source_before_publication_and_excludes_reposts(self):
        with closing(sqlite3.connect(self.corpus)) as c, c:
            c.execute("UPDATE raw_documents SET source_id='other' WHERE id=6")
            text=evidence.get_document(7).text
            c.execute('UPDATE raw_documents SET markdown=?,raw_content=? WHERE id=5',(text,text))
        result=reading.history(7)
        self.assertEqual([i.document.id for i in result.previous],[4,3,2])
        self.assertEqual(reading.history(1).previous,[])
        self.assertEqual(self.client.get(BASE+'/reading/999/history').status_code,404)
        self.assertEqual(self.client.get(BASE+'/reading?days=999').status_code,422)
        self.assertEqual(self.client.get(BASE+'/reading?days=7').status_code,200)

    def test_present_memory_investment_posture_is_included_without_product_jargon(self):
        with closing(sqlite3.connect(self.corpus)) as c, c:
            c.execute("UPDATE raw_documents SET title='현금 비중',markdown='삼성전자와 하이닉스를 줄이고 현금 비중을 늘렸습니다.' WHERE id=7")
        result=reading.reading(days=7,now=datetime(2026,8,8,tzinfo=timezone.utc))
        self.assertEqual(result.items[0].document.products,['memory'])
        self.assertTrue(reading.history(7).previous)

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

    def test_unrelated_whole_video_summary_does_not_replace_memory_passage(self):
        with closing(sqlite3.connect(self.corpus)) as c, c:
            c.execute('CREATE TABLE enrichments(id INTEGER PRIMARY KEY,doc_id INTEGER,summary TEXT)')
            c.execute('INSERT INTO enrichments VALUES(1,7,?)',('일본 금리 이야기만 요약됨',))
        result=reading.reading(days=7,now=datetime(2026,8,8,tzinfo=timezone.utc))
        self.assertIsNone(result.items[0].summary)
        self.assertIn('DRAM',result.items[0].excerpt)

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
