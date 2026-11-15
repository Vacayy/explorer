import struct
import unittest
from types import SimpleNamespace

from pipeline.postgres_related_documents import CentroidIndex, _shared_entities


def vector(x):
    return struct.pack('<384f', x, *([0.0] * 383))


class RelatedDocumentsTests(unittest.TestCase):
    def test_centroid_index_returns_nearest_and_handles_missing(self):
        index = CentroidIndex('fixture', [(1, vector(0)), (2, vector(0.1)), (3, vector(0.9))])
        try:
            self.assertEqual(index.nearest(999), [])
            self.assertEqual([row[0] for row in index.nearest(1)][:2], [1, 2])
        finally:
            index.close()

    def test_reasons_exclude_weak_stock_and_order_by_kind(self):
        rows = [({'doc_id': 1, 'entity_id': 4, 'link_type': 'industry', 'confidence': None}, {'name': '산업'}),
                ({'doc_id': 2, 'entity_id': 4, 'link_type': 'industry', 'confidence': None}, {'name': '산업'}),
                ({'doc_id': 1, 'entity_id': 5, 'link_type': 'stock', 'confidence': 0.4}, {'name': '낮은 신뢰'}),
                ({'doc_id': 2, 'entity_id': 5, 'link_type': 'stock', 'confidence': 0.4}, {'name': '낮은 신뢰'})]
        class Connection:
            def execute(self, sql, params):
                return SimpleNamespace(fetchall=lambda: [(4, 2)]) if 'count(*)' in sql else SimpleNamespace(fetchall=lambda: rows)
        self.assertEqual(_shared_entities(Connection(), 1, [2]), {2: ['산업']})


if __name__ == '__main__':
    unittest.main()
