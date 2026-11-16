"""Protect the local preview from mixing video identities or pinned snapshots."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

SCRIPT = Path('/opt/refactor-chat-write.py')
if not SCRIPT.exists():
    SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/refactor_chat_write_rehearsal.py'
spec = importlib.util.spec_from_file_location('refactor_chat_write_rehearsal', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class VideoOverlayTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(module.app)
        self.source = {'id': 7, 'source_type': 'youtube', 'url': 'https://example.test/v',
                       'title': 'video', 'published_at': '2026-01-01', 'transcript': 'captions',
                       'digest_status': 'pending', 'video_digest': None}
        self.copy = {**self.source, 'digest_status': 'ok', 'video_digest': 'saved summary'}

    def test_matching_unpinned_document_gets_saved_digest(self):
        with patch.object(module, 'source_document', return_value=(self.source.copy(), {})), \
             patch.object(module, 'copied_document', return_value=self.copy):
            result = self.client.get('/api/spine/doc/7')
        self.assertEqual(result.json()['video_digest'], 'saved summary')

    def test_pinned_document_stays_unchanged(self):
        with patch.object(module, 'source_document', return_value=(self.source.copy(), {'X-Explorer-Generation': 'g'})), \
             patch.object(module, 'copied_document') as copy:
            result = self.client.get('/api/spine/doc/7?generation=g')
        self.assertEqual(result.headers['X-Explorer-Generation'], 'g')
        self.assertEqual(result.json()['digest_status'], 'pending')
        copy.assert_not_called()

    def test_changed_transcript_rejects_generation(self):
        with patch.object(module, 'source_document', return_value=(self.source.copy(), {})), \
             patch.object(module, 'copied_document', return_value={**self.copy, 'transcript': 'different'}), \
             patch.object(module.spine_doc, 'generate_digest') as generate:
            result = self.client.post('/api/spine/doc/7/digest')
        self.assertEqual(result.status_code, 409)
        generate.assert_not_called()

    def test_changed_document_cannot_be_added_to_study(self):
        source = {**self.source, 'content': 'original body'}
        copy = {**source, 'content': 'different body'}
        with patch.object(module, 'source_document', return_value=(source, {})), \
             patch.object(module, 'copied_document', return_value=copy), \
             patch.object(module.spine_study_projects, 'add') as add:
            result = self.client.post('/api/spine/study-projects/3/documents', json={'document_ids': [7]})
        self.assertEqual(result.status_code, 409)
        add.assert_not_called()


if __name__ == '__main__':
    unittest.main()
