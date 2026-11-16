"""Question reports must reach the downstream scenario prompt."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pipeline import scenario


class ScenarioReportContextTests(unittest.TestCase):
    def test_question_report_is_in_actual_scenario_model_prompt(self):
        prompts=[]
        def model(prompt,**kwargs):
            prompts.append(prompt)
            return SimpleNamespace(text=json.dumps({'scenario':'시험 시나리오','beneficiaries':[],'causal':None}))
        conn=SimpleNamespace(close=lambda:None)
        with patch.object(scenario,'llm_engine',return_value='claude-code'), \
             patch.object(scenario,'get_connection',return_value=conn), \
             patch('pipeline.search.search',return_value=[]), \
             patch('pipeline.visibility.get_muted',return_value={}), \
             patch('pipeline.knowledge_recall.recall_for_query',return_value=[]), \
             patch('pipeline.narrative._node_vocab',return_value=[]), \
             patch('pipeline.llm.run',side_effect=model):
            result=scenario.build_scenario('가상 사건',report_context='직전 결산의 고유한 전제')
        self.assertNotIn('error',result)
        self.assertEqual(len(prompts),1)
        self.assertIn('직전 결산의 고유한 전제',prompts[0])

    def test_explicit_runtime_owns_all_data_and_write_paths(self):
        calls=[]
        class Runtime:
            def gather(self,event,*,limit):
                calls.append(('gather',event,limit))
                return ([{'id':5,'source_type':'blog','title':'시험 문서','url':'https://example.test','published_at':'2026-01-01','excerpt':'가상 자료'}],[],[])
            def run_llm(self,prompt,**kwargs):
                calls.append(('model',kwargs['task'],'결산의 전제' in prompt))
                return SimpleNamespace(text=json.dumps({'scenario':'시험 결과','beneficiaries':[{'name':'가상 기업'}], 'causal':{'nodes':[],'edges':[]}}))
            def resolve_beneficiaries(self,picks):
                calls.append(('beneficiary',len(picks)));return [{'name':'가상 기업','code':None}]
            def persist_causal(self,causal,*,conf_cap,source_status):
                calls.append(('graph',conf_cap,source_status))
        with patch.object(scenario,'get_connection',side_effect=AssertionError('legacy SQLite used')):
            result=scenario.build_scenario('가상 사건',report_context='결산의 전제',runtime=Runtime())
        self.assertEqual(result['citations'][0]['doc_id'],5)
        self.assertIn(('model','scenario.generate',True),calls)
        self.assertIn(('beneficiary',1),calls)
        self.assertIn(('graph',0.5,'scenario'),calls)

    def test_runtime_graph_failure_does_not_fall_back(self):
        class Runtime:
            def gather(self,event,*,limit):return [],[],[]
            def run_llm(self,prompt,**kwargs):return SimpleNamespace(text='{"scenario":"결과","causal":{"edges":[]}}')
            def persist_causal(self,*a,**kw):raise RuntimeError('graph unavailable')
        with patch.object(scenario,'get_connection',side_effect=AssertionError('legacy SQLite used')):
            with self.assertRaisesRegex(RuntimeError,'graph unavailable'):
                scenario.build_scenario('가상 사건',runtime=Runtime())
