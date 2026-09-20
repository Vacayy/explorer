import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from pipeline import study, study_coach as coach, llm
from routers.spine_study import StudyQuestion,Annotation

class CoachTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.db'
  self.patches=[patch.object(m,'get_connection',side_effect=self.connect) for m in (study,coach)]
  for p in self.patches:p.start()
  c=self.connect();c.executescript(study.SCHEMA+'''
  CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,title TEXT,url TEXT,source_type TEXT,published_at TEXT,markdown TEXT,raw_content TEXT);
  CREATE TABLE conversations(id INTEGER PRIMARY KEY,channel TEXT,title TEXT,state_json TEXT,updated_at TEXT);
  CREATE TABLE chat_messages(id INTEGER PRIMARY KEY,conversation_id INTEGER,role TEXT,content TEXT);
  INSERT INTO raw_documents VALUES(1,'AI 보안','https://example.com/a','youtube','2026-09-11',NULL,'공격과 방어 에이전트가 있다.');
  ''');c.commit();c.close();self.sid=study.open_document(1)['id']
  self.a=study.add_annotation(self.sid,Annotation(kind='highlight',start=0,end=5,exact='공격과 방',comment='어떻게 작동하나?'))
 def tearDown(self):
  for p in self.patches:p.stop()
  self.tmp.cleanup()
 def connect(self):
  c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;return c
 def question(self,key='coach-key-001',**kw):return StudyQuestion(question='설명해줘',annotations=[{'id':self.a['id'],'revision':1}],request_key=key,**kw)
 def complete(self,tid):
  c=self.connect();r=c.execute('SELECT conversation_id FROM study_turns WHERE id=?',(tid,)).fetchone();c.execute("UPDATE study_turns SET status='complete' WHERE id=?",(tid,));c.execute("INSERT INTO chat_messages(conversation_id,role,content) VALUES(?,'assistant','이전 답변')",(r[0],));c.commit();c.close()
 def test_identical_annotations_use_reference_instead_of_repeated_text(self):
  first=study.queue_turn(self.sid,self.question());self.complete(first['id'])
  second=study.queue_turn(self.sid,self.question('coach-key-002'))
  contexts=study.read_study(self.sid)['turns'];next=context=contexts[-1]['context']
  self.assertTrue(next['continuation']);self.assertEqual(next['context_ref'],first['id'])
  self.assertEqual(next['annotations'],[]);self.assertEqual(next['evidence'],[])
  self.assertNotIn('어떻게 작동하나?',json.dumps(next,ensure_ascii=False))
  self.assertEqual(coach.base_context(next)['annotations'][0]['comment'],'어떻게 작동하나?')
 def test_explicit_selection_resends_and_new_revision_does_not_deduplicate(self):
  first=study.queue_turn(self.sid,self.question());self.complete(first['id'])
  study.queue_turn(self.sid,self.question('coach-key-002',context_mode='selection'))
  self.assertFalse(study.read_study(self.sid)['turns'][-1]['context']['continuation'])
 def test_continue_requires_completed_turn_and_empty_followup_works(self):
  body=StudyQuestion(question='다른 자료는?',annotations=[],context_mode='continue',request_key='continue-key-01')
  with self.assertRaises(HTTPException):study.queue_turn(self.sid,body)
  first=study.queue_turn(self.sid,self.question());self.complete(first['id'])
  study.queue_turn(self.sid,body)
  self.assertEqual(study.read_study(self.sid)['turns'][-1]['context']['annotations'],[])
 def test_related_followup_forces_library_not_same_document_explanation(self):
  with patch.object(llm,'run',return_value=SimpleNamespace(text='{"intent":"coach","queries":["AI 보안 에이전트"]}')):
   result=coach.plan('관련해서 다룬 내용이 더 있나?','AI 보안','이전 설명','auto')
  self.assertEqual(result['intent'],'library')
 def test_web_only_accepts_actual_tool_results_not_generated_urls(self):
  result=SimpleNamespace(text='https://invented.example',tool_results=[{'name':'WebSearch','is_error':False,'content':'Links: [{"title":"공식 문서","url":"https://nvidia.com/research"}]'},{'name':'WebFetch','input':{'url':'https://nvidia.com/research'},'is_error':False,'content':'원문에서 확인한 연구 방법'}])
  with patch.object(llm,'llm_engine',return_value='claude-code'),patch.object(llm,'run',return_value=result):
   items,error=coach.web_evidence('public topic')
  self.assertIsNone(error);self.assertEqual(items[0]['href'],'https://nvidia.com/research')
  self.assertNotIn('invented',str(items))
 def test_no_search_results_are_not_reported_as_verified(self):
  with patch.object(llm,'llm_engine',return_value='claude-code'),patch.object(llm,'run',return_value=SimpleNamespace(text='검증 성공',tool_results=[])):
   items,error=coach.web_evidence('topic')
  self.assertEqual(items,[]);self.assertIn('검증 완료',error)
 def test_library_excludes_original_and_records_new_sources(self):
  from pipeline.chat import Turn
  first=study.queue_turn(self.sid,self.question());context=study.read_study(self.sid)['turns'][0]['context']
  turn=Turn(question='관련 소스가 더 있나?',conversation_id=first['conversation_id'],ctx={})
  result=SimpleNamespace(items=[{'doc_id':1,'href':'/doc/1','title':'원문','text':'원문'}, {'doc_id':2,'href':'/doc/2','title':'새 출처','text':'근거'}],note=None)
  with patch.object(coach,'plan',return_value={'intent':'library','queries':['AI 보안']}),patch('pipeline.chat_tools.search_docs',return_value=result) as search:
   coach.augment(turn,context,lambda _:None)
  search.assert_called_once();self.assertEqual(context['research']['results'][0]['doc_id'],2)
  self.assertFalse(any(e.get('doc_id')==1 for e in context['research']['results']))
 def test_coach_prompt_allows_explanation_but_forbids_rebriefing(self):
  from pipeline.chat import Turn,_synth_system
  t=Turn(question='설명',conversation_id=None,ctx={},route={'intent':'study'})
  prompt=_synth_system(t)
  self.assertIn('지도교수',prompt);self.assertIn('원문 재진술',prompt);self.assertIn('논리적 추론은 가능',prompt)

 def test_search_only_fallback_is_one_aggregate_not_duplicate_page_claims(self):
  result=SimpleNamespace(tool_results=[{'name':'WebSearch','content':'Links: [{"title":"첫 문서","url":"https://example.com/1"},{"title":"둘째","url":"https://example.com/2"}] REMINDER: tool instruction','is_error':False}])
  with patch.object(llm,'llm_engine',return_value='claude-code'),patch.object(llm,'run',return_value=result):items,note=coach.web_evidence('topic')
  self.assertEqual(len(items),1);self.assertIsNone(items[0]['href']);self.assertNotIn('REMINDER',items[0]['text']);self.assertIn('완료하지 못',note)
 def test_unsearched_fetch_url_cannot_become_evidence(self):
  result=SimpleNamespace(tool_results=[{'name':'WebFetch','input':{'url':'https://invented.example'},'content':'unsupported content','is_error':False}])
  with patch.object(llm,'llm_engine',return_value='claude-code'),patch.object(llm,'run',return_value=result):items,note=coach.web_evidence('topic')
  self.assertEqual(items,[]);self.assertTrue(note)

 def test_http_access_error_is_not_a_read_web_source(self):
  result=SimpleNamespace(tool_results=[
   {'name':'WebSearch','content':'Links: [{"title":"차단된 원문","url":"https://example.com/blocked"},{"title":"읽은 원문","url":"https://example.com/read"}]','is_error':False},
   {'name':'WebFetch','input':{'url':'https://example.com/blocked'},'content':'The server returned HTTP 403 Forbidden.\nThe response body was not retrieved.','is_error':False},
   {'name':'WebFetch','input':{'url':'https://example.com/read'},'content':'원문에서 확인한 연구 내용','is_error':False},
  ])
  with patch.object(llm,'llm_engine',return_value='claude-code'),patch.object(llm,'run',return_value=result):items,note=coach.web_evidence('topic')
  self.assertEqual([e['href'] for e in items],['https://example.com/read'])
  self.assertIn('접근하지 못',note)
