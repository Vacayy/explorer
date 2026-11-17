import struct
import unittest

from pipeline.postgres_search_snapshot import SearchSnapshot
from pipeline.postgres_search_feed import _sort_latest


def vector(x):
    return struct.pack('<384f', x, *([0.0] * 383))


class SearchSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.index = SearchSnapshot('fixture', [(1, '반도체 실적', '시장 전망'),
                                                 (2, '시장', '반도체 장비'),
                                                 (3, '다른 문서', '내용')],
                                    [(1, vector(0.0)), (2, vector(1.0)), (3, vector(4.0))])

    def tearDown(self):
        self.index.close()

    def test_lexical_fallback_and_empty_query(self):
        results = self.index.search('반도체', k=20)
        self.assertEqual({item['doc_id'] for item in results}, {1, 2})
        self.assertEqual(self.index.search(''), [])

    def test_hybrid_returns_vector_only_match_and_rejects_bad_vector(self):
        results = self.index.search('반도체', vector=vector(4.0), k=20)
        self.assertIn(3, [item['doc_id'] for item in results])
        with self.assertRaises(ValueError):
            self.index.search('반도체', vector=b'bad')
        with self.assertRaises(ValueError):
            self.index.search('반도체', vector=vector(float('nan')))

    def test_latest_keeps_legacy_rowid_order_for_equal_dates(self):
        rows = [(9, {'published_at': '2026-01-01'}, 'blog'),
                (2, {'published_at': '2026-01-01'}, 'blog'),
                (3, {'published_at': '2026-01-02'}, 'blog')]
        _sort_latest(rows)
        self.assertEqual([row[0] for row in rows], [3, 2, 9])

    def test_stale_vectors_are_filtered_against_streamed_document_hashes(self):
        class Result:
            def __init__(self, value):
                self.value = value
            def fetchone(self):
                return self.value

        class Cursor:
            def __init__(self, rows):
                self.rows = rows
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def execute(self, sql):
                self.sql = sql
                assert ' JOIN ' not in sql
            def __iter__(self):
                return iter(self.rows)

        class Connection:
            def execute(self, sql):
                if 'current_database' in sql:
                    return Result(('fixture', 'refactor_fixture_' + 'a' * 32))
                if 'transaction_isolation' in sql:
                    return Result(('repeatable read',))
                if 'transaction_read_only' in sql:
                    return Result(('on',))
                if 'snapshot_metadata' in sql:
                    return Result(('generation', 3))
                if 'document_embedding_metadata' in sql:
                    return Result(('generation', 4, 1, 0))
                if 'count(*) FROM document_embeddings' in sql:
                    return Result((4,))
                raise AssertionError(sql)
            def cursor(self, name):
                if name == 'fixture_search_documents':
                    return Cursor([(1, 'one', 'a', 'same'), (2, 'two', 'b', 'new'), (3, 'three', 'c', None)])
                return Cursor([(1, vector(0), 'same'), (2, vector(1), 'old'),
                               (3, vector(2), None), (4, vector(3), 'orphan')])

        index = SearchSnapshot.from_postgres(Connection(), allow_stale=True)
        try:
            self.assertEqual(index.db.execute('SELECT count(*) FROM doc_vec').fetchone()[0], 1)
            self.assertEqual(index.excluded_vectors, 3)
            self.assertEqual([x['doc_id'] for x in index.search('one')], [1])
        finally:
            index.close()


if __name__ == '__main__':
    unittest.main()
