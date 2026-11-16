"""An injected chat data backend must not silently read SQLite."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pipeline import chat
from pipeline.chat_tools import ToolResult


class FakeRuntime:
    def __init__(self):
        self.document_ids = None
        self.tool_calls = []

    def attached_evidence(self, ids):
        self.document_ids = ids
        return [{'kind': 'doc', 'doc_id': ids[0], 'title': 'fixture', 'text': 'fixture body',
                 'tool': 'attached_documents'}]

    def gather_attached_refs(self, refs):
        return [], []

    def run_tool(self, call):
        self.tool_calls.append(call)
        return ToolResult(call['name'], call['args'], [{'kind': 'doc', 'doc_id': 8, 'text': 'search result'}])


class InjectedRuntimeTests(unittest.TestCase):
    def test_attached_document_and_search_use_injected_backend(self):
        runtime = FakeRuntime()
        ctx = {'state': {'attached_doc_ids': [7]}, 'note': None, 'recent': [], 'related': []}

        def route(turn, status):
            turn.route = {'intent': 'research'}
            turn.calls = [{'name': 'search_docs', 'args': {'query': 'fixture'}}]

        with patch.object(chat, '_route', side_effect=route), \
             patch.object(chat, '_review'), patch.object(chat, '_synthesize'), patch.object(chat, '_verify'), \
             patch.object(chat, 'get_connection', side_effect=AssertionError('SQLite must not be used')), \
             patch.object(chat, 'run_tool', side_effect=AssertionError('default tool must not be used')):
            turn = chat.run_turn('question', ctx=ctx, runtime=runtime)
        self.assertEqual(runtime.document_ids, [7])
        self.assertEqual(runtime.tool_calls[0]['name'], 'search_docs')
        self.assertEqual([item['doc_id'] for item in turn.evidence], [7, 8])

    def test_injected_runtime_requires_explicit_context(self):
        with self.assertRaises(ValueError):
            chat.run_turn('question', runtime=FakeRuntime())

    def test_model_routing_uses_injected_recorder_and_fails_closed(self):
        runtime = FakeRuntime()
        calls = []
        runtime.run_llm = lambda *args, **kwargs: (calls.append(kwargs['task']) or
            SimpleNamespace(text='{"intent":"research","tools":[]}'))
        turn = chat.Turn(question='q', conversation_id=1, ctx={}, runtime=runtime)
        chat._route(turn, lambda _: None)
        self.assertEqual(calls, ['chat.route'])

        def failed(*args, **kwargs):
            raise chat.llm.CallRecordingError('recording failed')
        runtime.run_llm = failed
        with self.assertRaises(chat.llm.CallRecordingError):
            chat._route(turn, lambda _: None)
