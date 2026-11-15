"""Characterization of the existing document detail contract on synthetic data."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from routers import spine_doc


class DocumentReadBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'documents.sqlite'
        conn = self.connect()
        conn.executescript('''
            CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,source_type TEXT,source_id TEXT,
              title TEXT,url TEXT,published_at TEXT,markdown TEXT,raw_content TEXT,
              digest_status TEXT,media_json TEXT);
            CREATE TABLE enrichments(id INTEGER PRIMARY KEY,doc_id INTEGER,summary TEXT,
              model TEXT,enriched_at TEXT);
            CREATE TABLE entities(id INTEGER,type TEXT,name TEXT,aliases TEXT);
            CREATE TABLE entity_links(doc_id INTEGER,entity_id INTEGER,link_type TEXT,confidence REAL);
            INSERT INTO raw_documents VALUES
              (1,'blog','synthetic','제목','https://example.test/article','2026-01-01',
               '원문', '원본', NULL, '["fixtures/example.jpg"]'),
              (2,'note','synthetic-2',NULL,NULL,NULL,NULL,'대체 원문',NULL,NULL);
            INSERT INTO enrichments VALUES
              (1,1,'예전 요약','old','2026-01-01'),
              (2,1,'저장된 요약','model','2026-01-02');
            INSERT INTO entities VALUES (7,'company','합성 회사','000000');
            INSERT INTO entity_links VALUES (1,7,'stock',0.8);
        ''')
        conn.commit()
        conn.close()
        self.patcher = patch.object(spine_doc, 'get_connection', side_effect=self.connect)
        self.patcher.start()
        self.channel = patch('routers.spine_feed.resolve_channels', return_value={1: {
            'name': '합성 채널', 'kind': 'blog', 'key': 'https://example.test/'}})
        self.channel.start()

    def tearDown(self):
        self.channel.stop()
        self.patcher.stop()
        self.temp.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_detail_keeps_original_summary_attachment_and_entity(self):
        doc = spine_doc.get_document(1)
        self.assertEqual((doc.id, doc.content, doc.summary), (1, '원문', '저장된 요약'))
        self.assertEqual(doc.images, ['fixtures/example.jpg'])
        self.assertEqual((doc.channel, doc.channel_kind), ('합성 채널', 'blog'))
        self.assertEqual([(e.entity_id, e.link_type) for e in doc.entities], [(7, 'stock')])

    def test_raw_fallback_and_missing(self):
        doc = spine_doc.get_document(2)
        self.assertEqual((doc.content, doc.title, doc.images), ('대체 원문', '', []))
        with self.assertRaises(HTTPException) as error:
            spine_doc.get_document(999)
        self.assertEqual(error.exception.status_code, 404)


if __name__ == '__main__':
    unittest.main()
