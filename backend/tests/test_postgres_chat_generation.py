import unittest
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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

    def test_concurrent_generations_do_not_overlap(self):
        store = Mock()
        store.load_context.return_value = {}
        guard = threading.Lock()
        state = {'active': 0, 'peak': 0}
        turn = SimpleNamespace(answer='답변', citations=[], gaps=[], model='test',
                               route={'intent': 'research', 'entities': []}, calls=[], route_log=lambda: {})

        def run(*_args, **_kwargs):
            with guard:
                state['active'] += 1
                state['peak'] = max(state['peak'], state['active'])
            time.sleep(0.03)
            with guard:
                state['active'] -= 1
            return turn

        with patch('pipeline.chat.run_turn', side_effect=run), ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(lambda ident: generate_answer(store, Mock(), ident, '질문'), (10, 11)))
        self.assertEqual(state['peak'], 1)
        self.assertEqual([answer['answer'] for answer in answers], ['답변', '답변'])


if __name__ == '__main__':
    unittest.main()
