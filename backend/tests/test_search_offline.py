"""An interactive library read still returns BM25 hits without cached embeddings."""
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from pipeline import search, chunks, rerank


class OfflineSearchTests(unittest.TestCase):
    def test_uncached_model_never_downloads_or_discards_keyword_hits(self):
        c = sqlite3.connect(':memory:')
        c.row_factory = sqlite3.Row
        c.execute('CREATE VIRTUAL TABLE doc_fts USING fts5(title)')
        c.execute("INSERT INTO doc_fts(rowid,title) VALUES(7,'NVLink scale up')")
        vector = MagicMock()
        vector.execute.return_value.fetchone.return_value = [1]
        with patch.object(search, 'get_connection', return_value=c), \
             patch.object(search, '_vec_conn', return_value=vector), \
             patch.object(search, '_get_model', side_effect=ValueError('not cached')) as model:
            result = search.search('NVLink')
        self.assertEqual([r['doc_id'] for r in result], [7])
        model.assert_called_once_with(local_files_only=True)
        vector.close.assert_called_once()

    def test_chunk_search_keeps_keyword_passage_without_vector_model(self):
        with tempfile.NamedTemporaryFile() as f:
            def connect():
                c = sqlite3.connect(f.name); c.row_factory = sqlite3.Row; return c
            c = connect()
            c.executescript('''CREATE VIRTUAL TABLE chunk_fts USING fts5(text);
                CREATE TABLE doc_chunks(id INTEGER, doc_id INTEGER, prefix TEXT, text TEXT);
                INSERT INTO chunk_fts(rowid,text) VALUES(2,'NVLink scale up');
                INSERT INTO doc_chunks VALUES(2,7,'자료 출처','NVLink scale up');''')
            c.close()
            vector = MagicMock(); vector.execute.return_value.fetchone.return_value = [1]
            with patch.object(chunks, 'get_connection', side_effect=connect), \
                 patch.object(chunks, '_vec_conn', return_value=vector), \
                 patch.object(chunks, '_get_model', side_effect=ValueError('not cached')) as model:
                result = chunks.search_chunks('NVLink')
            self.assertEqual(result[0]['text'], 'NVLink scale up')
            model.assert_called_once_with(local_files_only=True)
            vector.close.assert_called_once()

    def test_uncached_reranker_preserves_retrieval_order(self):
        with patch.object(rerank, '_enc', None), patch.object(rerank, '_failed', False), \
             patch('fastembed.rerank.cross_encoder.TextCrossEncoder', side_effect=ValueError('not cached')) as encoder:
            self.assertIsNone(rerank.rerank('NVLink', ['관련 자료']))
            encoder.assert_called_once_with(rerank.RERANK_MODEL, local_files_only=True)


if __name__ == '__main__':
    unittest.main()
