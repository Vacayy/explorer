import unittest
from unittest.mock import Mock

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
