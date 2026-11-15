import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pipeline.postgres_document_claims import claims_state


class FakeConnection:
    def __init__(self, saved=None, captured=True):
        self.saved, self.captured = saved, captured

    def execute(self, sql, params=()):
        if 'legacy_snapshot_tables' in sql:
            result = (1,) if self.captured else None
        elif "table_name='doc_claims'" in sql:
            result = (self.saved,) if self.saved else None
        else:
            result = ({'content_hash': 'current', 'source_type': 'blog', 'title': None,
                       'published_at': None},) if params[0] in ('1', '2') else None
        return SimpleNamespace(fetchone=lambda: result)


class ClaimsTests(unittest.TestCase):
    def test_uncaptured_refused_and_missing_document(self):
        with self.assertRaises(ValueError):
            claims_state(FakeConnection(captured=False), 1)
        self.assertIsNone(claims_state(FakeConnection(), 99))

    def test_stale_content_and_interrupted_job(self):
        self.assertEqual(claims_state(FakeConnection({'status': 'ok', 'content_hash': 'old'}), 1)['status'], 'none')
        state = claims_state(FakeConnection({'status': 'running', 'updated_at': 1}), 1, now=1000)
        self.assertEqual(state['status'], 'failed')
        self.assertTrue(state['error'])

    def test_saved_claims_preserve_nullable_metadata_and_omit_missing_related(self):
        payload = {'claims': [{'claim': 'a', 'related': [{'id': 2, 'score': 1.0}, {'id': 3, 'score': 0.5}]}]}
        saved = {'status': 'ok', 'content_hash': 'current', 'payload': json.dumps(payload)}
        with patch('pipeline.postgres_document_claims.PostgreSQLRawDocumentReader') as reader:
            reader.return_value.get_in_transaction.side_effect = lambda _, ident: SimpleNamespace(channel='channel') if ident == 2 else None
            state = claims_state(FakeConnection(saved), 1)
        self.assertEqual(len(state['claims'][0]['related']), 1)
        self.assertIsNone(state['claims'][0]['related'][0]['title'])


if __name__ == '__main__':
    unittest.main()
