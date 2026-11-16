"""Study evidence uses the injected store and tools, never legacy SQLite."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pipeline import chat, study_coach
from pipeline.chat_tools import ToolResult


class Runtime:
    def __init__(self): self.calls=[]
    def base_study_context(self, context):
        self.calls.append('base');return context
    def study_document_ids(self, ids):
        self.calls.append(('ids',ids));return {11}
    def study_search(self, query, *, k):
        self.calls.append(('search',query,k))
        return ToolResult('search_docs',{},[{'doc_id':11,'title':'excluded'}, {'doc_id':12,'title':'other','href':'/doc/12','text':'evidence'}],None)
    def run_llm(self, prompt, **kwargs):
        self.calls.append(('llm',kwargs.get('task')))
        return SimpleNamespace(text='{"intent":"library","queries":["topic"]}')


class InjectedStudyTests(unittest.TestCase):
    def test_study_uses_injected_search_and_preserves_original_exclusion(self):
        runtime=Runtime()
        context={'study_id':4,'scope':'본문', 'research_mode':'library',
                 'evidence':[{'title':'원문','text':'본문'}], 'annotations':[]}
        with patch.object(study_coach,'get_connection',side_effect=AssertionError('SQLite called')), \
             patch.object(chat,'_synthesize'), patch.object(chat,'_verify'):
            turn=chat.run_turn('관련 자료',conversation_id=1,ctx={},study_context=context,runtime=runtime)
        self.assertEqual([e.get('doc_id') for e in turn.evidence],[None,12])
        self.assertIn(('search','topic',5),runtime.calls)
        self.assertIn(('llm','study.plan'),runtime.calls)
        self.assertEqual(context['research']['intent'],'library')

    def test_study_annotation_action_is_explicitly_unsupported(self):
        with self.assertRaises(NotImplementedError):
            chat.run_turn('질문',ctx={},runtime=Runtime(),study_context={'study_intent':'explain'})
