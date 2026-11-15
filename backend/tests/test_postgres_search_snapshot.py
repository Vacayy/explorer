import struct
import unittest

from pipeline.postgres_search_snapshot import SearchSnapshot


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


if __name__ == '__main__':
    unittest.main()
