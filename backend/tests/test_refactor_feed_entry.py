import importlib.util
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import time
import unittest
from unittest.mock import MagicMock, patch

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
        reader.assert_called_once_with(page=1, size=1, source='scrap', stock=None, industry=None, topic=None, days=None)

    def test_no_query_entity_and_date_filters_are_forwarded(self):
        value = FeedResponse(items=[], total=0, page=1, size=20, as_of='2026-01-01', facets=None)
        with patch.object(self.module.list_reader, 'list', return_value=value) as reader:
            response = self.client.get('/api/spine/feed', params={'stock': '005930', 'days': 30})
        self.assertEqual(response.status_code, 200)
        reader.assert_called_once_with(page=1, size=20, source=None, stock='005930', industry=None, topic=None, days=30)

    def test_search_generation_change_failure_and_concurrent_requests(self):
        current = {'generation': 'a'}
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, sql):
                return SimpleNamespace(fetchone=lambda: (current['generation'],))
        def index(generation):
            result = MagicMock()
            result.generation = generation
            return result
        first, second = index('a'), index('b')
        def build(_):
            time.sleep(0.04)
            if current['generation'] == 'failure':
                raise ValueError('index build failed')
            return first if current['generation'] == 'a' else second
        value = FeedResponse(items=[], total=0, page=1, size=20, as_of='2026-01-01', facets=None)
        client = TestClient(self.module.app, raise_server_exceptions=False)
        self.module.search_index = None
        try:
            with patch.object(self.module, 'factory', side_effect=Connection), \
                    patch.object(self.module.SearchSnapshot, 'from_postgres', side_effect=build) as builder, \
                    patch.object(self.module, 'search_feed', return_value=value), \
                    patch('pipeline.search._get_model', side_effect=RuntimeError('offline')):
                with ThreadPoolExecutor(max_workers=6) as pool:
                    responses = list(pool.map(lambda _: client.get('/api/spine/feed', params={'q': 'test'}), range(6)))
                self.assertTrue(all(r.status_code == 200 for r in responses))
                self.assertEqual(builder.call_count, 1)
                current['generation'] = 'failure'
                self.assertEqual(client.get('/api/spine/feed', params={'q': 'test'}).status_code, 500)
                first.close.assert_not_called()
                current['generation'] = 'a'
                self.assertEqual(client.get('/api/spine/feed', params={'q': 'test'}).headers['x-explorer-generation'], 'a')
                current['generation'] = 'b'
                self.assertEqual(client.get('/api/spine/feed', params={'q': 'test'}).headers['x-explorer-generation'], 'b')
                first.close.assert_called_once()
        finally:
            self.module.search_index = None


if __name__ == '__main__':
    unittest.main()
