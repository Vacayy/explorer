import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from models.spine import FeedResponse


class FeedEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = Path(__file__).resolve().parents[2] / 'scripts/refactor_document_ui.py'
        spec = importlib.util.spec_from_file_location('refactor_document_ui_test', script)
        cls.module = importlib.util.module_from_spec(spec)
        settings = {'REFACTOR_POSTGRES_DSN': 'host=pg dbname=fixture user=fixture',
                    'REFACTOR_FIXTURE_SCHEMA': 'refactor_fixture_' + 'a' * 32,
                    'REFACTOR_TEST_DISPOSABLE': '1'}
        with patch.dict(os.environ, settings):
            spec.loader.exec_module(cls.module)
        cls.client = TestClient(cls.module.app)

    def test_no_query_loads_existing_feed_and_source_count(self):
        value = FeedResponse(items=[], total=17, page=1, size=1, as_of='2026-01-01', facets=None)
        with patch.object(self.module.list_reader, 'list', return_value=value) as reader:
            response = self.client.get('/api/spine/feed', params={'source': 'scrap', 'size': 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['total'], 17)
        reader.assert_called_once_with(page=1, size=1, source='scrap')

    def test_unimplemented_no_query_entity_filter_is_not_silently_ignored(self):
        response = self.client.get('/api/spine/feed', params={'stock': '005930'})
        self.assertEqual(response.status_code, 501)


if __name__ == '__main__':
    unittest.main()
