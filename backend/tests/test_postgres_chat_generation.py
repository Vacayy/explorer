import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pipeline.postgres_chat_generation import generate_answer


class GenerationTests(unittest.TestCase):
    def test_answer_and_memory_use_pg_store(self):
        store = Mock()
        store.load_context.return_value = {'state': {}, 'recent': [], 'related': [], 'note': None}
        tools = Mock()
        tools.chunk_rag.entity_scope.return_value = (3, ['기업'], {})
        turn = SimpleNamespace(answer='답변', citations=[], gaps=[], model='test',
                               route={'intent': 'research', 'entities': [{'name': '기업'}]},
                               calls=[{'name': 'search_docs'}], route_log=lambda: {'intent': 'research'})
        with patch('pipeline.chat.run_turn', return_value=turn) as run:
            result = generate_answer(store, tools, 4, '질문')
        self.assertEqual(result['answer'], '답변')
        store.append_assistant.assert_called_once()
        self.assertEqual(store.update_state.call_args.kwargs['entities'][0]['id'], 3)
        self.assertIsNotNone(run.call_args.kwargs['runtime'])

    def test_failure_finishes_stream_and_does_not_expose_exception(self):
        store = Mock()
        store.load_context.return_value = {}
        with patch('pipeline.chat.run_turn', side_effect=RuntimeError('sensitive detail')):
            result = generate_answer(store, Mock(), 5, '질문')
        self.assertNotIn('sensitive', result['error'])
        self.assertTrue(__import__('pipeline.chat', fromlist=['get_stream']).get_stream(5).done)


if __name__ == '__main__':
    unittest.main()
