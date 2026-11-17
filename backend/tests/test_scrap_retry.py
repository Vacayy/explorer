import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.connectors.scrap import ScrapConnector
from pipeline.base import RawDoc, SourceRef


class ScrapRetryTest(unittest.TestCase):
    def test_unfinished_ledger_entries_retry_even_outside_message_window(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'test.sqlite')

            def connection():
                conn = sqlite3.connect(path)
                conn.row_factory = sqlite3.Row
                return conn

            conn = connection()
            conn.executescript('''
                CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, source_type TEXT,
                    source_id TEXT, markdown TEXT, published_at TEXT, url TEXT);
                CREATE TABLE scrap_links(url TEXT PRIMARY KEY, channel TEXT, src_doc_id INTEGER,
                    status TEXT, tries INTEGER DEFAULT 0, doc_id INTEGER,
                    seen_count INTEGER DEFAULT 1, last_seen_at TEXT);
                INSERT INTO raw_documents VALUES (1,'telegram','c/1','', '2000-01-01',NULL);
                INSERT INTO scrap_links(url,channel,src_doc_id,status,tries,doc_id) VALUES
                    ('https://example.test/a','c',1,'pending',0,NULL),
                    ('https://example.test/b','c',1,'ok',1,NULL),
                    ('https://example.test/c','c',1,'ok',1,42),
                    ('https://example.test/d','c',1,'failed',3,NULL);
            ''')
            conn.commit()
            conn.close()
            connector = ScrapConnector(['c'])
            with patch('pipeline.connectors.scrap.get_connection', connection), \
                 patch('pipeline.connectors.scrap.time.sleep'), \
                 patch.object(connector, '_fetch_one', side_effect=lambda url, *_: RawDoc('scrap', url)):
                docs = connector.fetch(SourceRef(key='c'))
            self.assertEqual({doc.source_id for doc in docs},
                             {'https://example.test/a', 'https://example.test/b'})
