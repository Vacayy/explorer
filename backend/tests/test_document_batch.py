"""The batched SQLite reader must preserve existing document responses."""
import unittest
from contextlib import closing

from pipeline.document_read import _read_sqlite_document, _read_sqlite_documents
import tests.test_document_read_boundary as detail_fixtures


class DocumentBatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = detail_fixtures.DocumentReadBoundaryTests('test_raw_fallback_and_missing')
        self.fixture.setUp()
        with closing(self.fixture.connect()) as c:
            c.execute("INSERT INTO raw_documents VALUES(3,'youtube','yt/3','영상',NULL,'2026-01-03','정리본','자막','ok',NULL)")
            c.execute("INSERT INTO raw_documents VALUES(4,'youtube','yt/4','영상2',NULL,'2026-01-04',NULL,'원 자막','pending',NULL)")
            c.execute("INSERT INTO youtube_digest_jobs VALUES(4,'원 자막','failed','fixture',0,'합성 오류')")
            c.commit()

    def tearDown(self):
        self.fixture.tearDown()

    def test_same_content_order_duplicates_missing_and_youtube(self):
        ids = [4, 1, 999, 2, 3, 1]
        with closing(self.fixture.connect()) as c:
            expected = [_read_sqlite_document(c, i) for i in ids]
            actual = list(_read_sqlite_documents(c, ids, batch_size=2))
        encode = lambda item: item.model_dump() if item is not None else None
        self.assertEqual([encode(x) for x in actual], [encode(x) for x in expected])
        self.assertEqual(actual[0].digest_status, 'failed')
        self.assertEqual(actual[4].video_digest, '정리본')

    def test_empty_and_invalid_batch_size(self):
        with closing(self.fixture.connect()) as c:
            self.assertEqual(list(_read_sqlite_documents(c, [])), [])
            with self.assertRaises(ValueError):
                list(_read_sqlite_documents(c, [1], batch_size=0))


if __name__ == '__main__':
    unittest.main()
