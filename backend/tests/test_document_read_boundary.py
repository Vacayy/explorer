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
            CREATE TABLE telegram_channels(channel_name TEXT,display_name TEXT,is_active INTEGER);
            CREATE TABLE blog_sources(url TEXT,platform TEXT,blog_name TEXT,is_active INTEGER);
            CREATE TABLE youtube_channels(channel_id TEXT,title TEXT,is_active INTEGER);
            CREATE TABLE scrap_links(doc_id INTEGER,channel TEXT);
            CREATE TABLE follows(entity_id INTEGER);
            CREATE TABLE youtube_digest_jobs(doc_id INTEGER,transcript TEXT,status TEXT,token TEXT,updated_at REAL,error TEXT);
            CREATE TABLE entity_digests(id INTEGER,entity_id INTEGER,period TEXT,period_start TEXT,digest TEXT,doc_count INTEGER,created_at TEXT);
            CREATE TABLE source_digests(id INTEGER,kind TEXT,key TEXT,digest TEXT,doc_count INTEGER,created_at TEXT);
            CREATE TABLE transcripts(id INTEGER,raw_doc_id INTEGER,ticker TEXT,fiscal_year INTEGER,fiscal_period TEXT,digest TEXT,fetched_at TEXT);
            CREATE TABLE transcript_follow(ticker TEXT,company_name TEXT,active INTEGER);
            CREATE TABLE trade_stats(hs_code TEXT,period TEXT,fetched_at TEXT);
            CREATE TABLE trade_follow(hs_code TEXT,item_name TEXT,group_label TEXT,active INTEGER);
            CREATE TABLE narratives(id INTEGER,topic TEXT,version INTEGER,title TEXT,body TEXT,doc_count INTEGER,created_at TEXT);
            CREATE TABLE reports(id INTEGER,anchor_topic TEXT,title TEXT,body TEXT,members_json TEXT,created_at TEXT);
            CREATE TABLE scenarios(topic TEXT,answer TEXT,question_id INTEGER,created_at TEXT);
            CREATE TABLE channel_reads(channel TEXT,read_until TEXT,updated_at TEXT);
            INSERT INTO entity_digests VALUES (1,7,'1d','2026-01-01','합성 요약',1,'2026-01-02');
            INSERT INTO channel_reads VALUES ('blog:fixture','2026-01-02',NULL);
            INSERT INTO raw_documents VALUES
              (1,'blog','synthetic','제목','https://example.test/article','2026-01-01',
               '원문', '원본', NULL, '["fixtures/example.jpg"]'),
              (2,'note','synthetic-2',NULL,NULL,NULL,NULL,'대체 원문',NULL,NULL);
            INSERT INTO enrichments VALUES
              (1,1,'예전 요약','old','2026-01-01'),
              (2,1,'저장된 요약','model','2026-01-02');
            INSERT INTO entities VALUES (7,'company','합성 회사','000000');
            INSERT INTO entity_links VALUES (1,7,'stock',0.8);
            INSERT INTO blog_sources VALUES ('https://example.test/','naver','합성 채널',1);
        ''')
        conn.commit()
        conn.close()
        self.patcher = patch.object(spine_doc, 'get_connection', side_effect=self.connect)
        self.patcher.start()
        self.channel = patch('routers.spine_feed.resolve_channels', return_value={1: {
            'name': '합성 채널', 'kind': 'blog', 'key': 'https://example.test/'},
            2: {'name': '내 노트', 'kind': None, 'key': None},
            3: {'name': 'YouTube', 'kind': None, 'key': None},
            4: {'name': 'YouTube', 'kind': None, 'key': None}})
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
