import unittest
from unittest.mock import MagicMock, Mock, patch

from pipeline.rag import retrieve_docs
class ChunkRAGTests(unittest.TestCase):
    def test_retrieval_uses_injected_search_filter_and_reranker(self):
        runtime = Mock()
        runtime.chunk_index_ready.return_value = True
        runtime.search_chunks.return_value = [
            {'doc_id': i, 'chunk_id': i, 'prefix': 'prefix', 'text': str(i) * 90} for i in (1, 2)]
        runtime.fetch_docs.return_value = [{'id': i, 'title': str(i)} for i in (1, 2)]
        runtime.apply_filters.side_effect = lambda docs, *args: docs
        runtime.rerank.return_value = [0.1, 0.9]
        results = retrieve_docs('query', variants=['variant'], source='blog', runtime=runtime)
        self.assertEqual([r['id'] for r in results], [2, 1])
        self.assertEqual([r['rerank_score'] for r in results], [0.9, 0.1])
        self.assertEqual(runtime.search_chunks.call_args.kwargs['pool'], 320)
        self.assertEqual(runtime.rerank.call_args.args[0], 'query (variant)')

    def test_missing_injected_index_never_falls_back_to_sqlite(self):
        runtime = Mock()
        runtime.chunk_index_ready.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'no chunk index'):
            retrieve_docs('query', runtime=runtime)

    def test_chat_tool_uses_chunk_rag_and_keeps_filters_explicit(self):
        from pipeline.postgres_chat_tools import PostgreSQLChatTools, UnsupportedPostgresChatTool
        runtime = Mock()
        tools = PostgreSQLChatTools(Mock(), None, chunk_rag=runtime)
        docs = [{'id': 7, 'title': '문서', 'excerpt': '근거', 'published_at': '2026-01-01', 'source_type': 'blog'}]
        with patch('pipeline.rag.retrieve_docs', return_value=docs) as retrieve:
            result = tools.run_tool({'name': 'search_docs', 'args': {'query': '질문', 'source': 'blog'}})
        self.assertEqual(result.items[0]['doc_id'], 7)
        self.assertIs(retrieve.call_args.kwargs['runtime'], runtime)
        with self.assertRaises(UnsupportedPostgresChatTool):
            PostgreSQLChatTools(Mock(), None, allow_lexical_only=True).run_tool(
                {'name': 'search_docs', 'args': {'query': '질문', 'entity': '기업'}})
        runtime.channel_scope.return_value = ({7}, ['채널'], '수집 범위')
        with patch('pipeline.rag.retrieve_docs', return_value=docs) as retrieve:
            tools.run_tool({'name': 'search_docs', 'args': {'query': '질문', 'channel': '채널'}})
        self.assertEqual(retrieve.call_args.kwargs['doc_ids'], {7})
        runtime.entity_scope.return_value = (3, ['기업', 'ABC'], {})
        with patch('pipeline.rag.retrieve_docs', return_value=docs) as retrieve:
            tools.run_tool({'name': 'search_docs', 'args': {'query': '질문', 'entity': '기업'}})
        self.assertEqual(retrieve.call_args.kwargs['entity_id'], 3)
        self.assertEqual(retrieve.call_args.kwargs['entity_terms'], ['기업', 'ABC'])

    def test_narrative_tool_resolves_alias_and_returns_existing_contract(self):
        from pipeline.postgres_chat_tools import PostgreSQLChatTools
        from routers.spine_narrative import Narrative
        rag = Mock()
        rag.entity_scope.return_value = (3, ['정식 주제'], {})
        tools = PostgreSQLChatTools(MagicMock(), None, chunk_rag=rag)
        with patch('pipeline.postgres_narrative_fixture.cached_narrative', side_effect=[
            Narrative(status='not_found'),
            Narrative(status='cached', title='시험 내러티브', narrative='시험 본문', created_at='2026-01-01', stale=False),
        ]):
            result = tools.run_tool({'name': 'get_narrative', 'args': {'topic': '별칭'}})
        self.assertEqual(result.args['topic'], '정식 주제')
        self.assertEqual(result.items[0]['text'], '시험 본문')
        self.assertFalse(result.items[0]['stale'])

    def test_shared_filters_preserve_existing_mute_and_entity_rules(self):
        from pipeline.rag import _filter_with_settings
        docs = [dict(id=1, source_type='telegram', source_id='muted/1', url='', published_at='2026-01-01'),
                dict(id=2, source_type='blog', source_id='', url='https://example.com/a', published_at='2026-01-01'),
                dict(id=3, source_type='scrap', source_id='', url='', published_at='2026-01-01')]
        result = _filter_with_settings(docs, None, None, {1, 2, 3}, {1, 2, 3},
                                       {'telegram': {'muted'}, 'blog': []})
        self.assertEqual([doc['id'] for doc in result], [2])
        self.assertEqual(_filter_with_settings(docs, None, 'blog', {1}, None,
                                               {'telegram': set(), 'blog': []}), [])


if __name__ == '__main__':
    unittest.main()
