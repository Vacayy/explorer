import sqlite3
import unittest
from unittest.mock import patch

from pipeline import telegram_deferred as deferred
from pipeline.connectors.telegram import TelegramConnector


class TelegramDeferredTest(unittest.TestCase):
    def test_page_snapshot_stays_available_without_a_new_source_request(self):
        messages = [{'message_id': '1', 'content': 'test', 'date': '2026-01-01T00:00:00Z',
                     'link': 'https://example.test', 'images': []}]
        ref = deferred.page_reference('channel', messages)
        with patch('pipeline.connectors.telegram.scrape_channel', side_effect=AssertionError('unexpected request')):
            docs = TelegramConnector().fetch(ref)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].raw_content, 'test')

    def test_missing_group_or_image_analysis_is_deferred(self):
        with self.assertRaises(deferred.NeedsAnalysis):
            deferred.no_new_group_decision('', '', 0)
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.execute('CREATE TABLE image_readings(image_key TEXT,status TEXT,attempts INTEGER)')
        with patch.object(deferred, 'get_connection', return_value=conn):
            with self.assertRaises(deferred.NeedsAnalysis):
                deferred.cached_images([{'key': 'missing'}])
