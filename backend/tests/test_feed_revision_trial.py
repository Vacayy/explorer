import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from pipeline.base import RawDoc, SourceRef
from pipeline.feed_backlog import FeedBacklog
from pipeline.feed_revision_trial import stage_one


class RevisionTrialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.queue = FeedBacklog(Path(self.tmp.name) / 'queue'); self.addCleanup(self.queue.close)
        self.ref = SourceRef('synthetic-ref', meta={'post': {'url': 'https://example.test/post'}})
        self.queue.enqueue_ref('blog', 'feed', self.ref, revision_pending=True)

    def test_snapshot_and_original_reference_remain_pending(self):
        class Connector:
            def fetch_post(self, ref): return RawDoc('blog', 'https://example.test/post', raw_content='synthetic-new')
        called = []
        result = stage_one(self.queue, Connector(), lambda *_: True, lambda: called.append(True))
        self.assertEqual(result['revision_snapshot'], 1)
        self.assertEqual(called, [True])
        self.assertIsNone(self.queue.next())
        self.assertEqual(self.queue.conn.execute('SELECT count(*) FROM pending_refs WHERE revision_pending=1').fetchone()[0], 1)
        payload, pending = self.queue.conn.execute('SELECT payload,revision_pending FROM pending').fetchone()
        self.assertEqual(pending, 1)
        self.assertEqual(json.loads(payload)['raw_content'], 'synthetic-new')

    def test_does_not_replace_image_analysis_pending(self):
        self.queue.enqueue('blog', 'feed', RawDoc('blog', 'https://example.test/post', raw_content='old'))
        self.queue.defer_revision(self.queue.next()[0], reason='analysis')
        class Connector:
            def fetch_post(self, ref): raise AssertionError('must not fetch')
        self.assertEqual(stage_one(self.queue, Connector(), lambda *_: True, lambda: None)['revision_snapshot'], 0)
        payload = self.queue.conn.execute('SELECT payload FROM pending').fetchone()[0]
        self.assertEqual(json.loads(payload)['raw_content'], 'old')

    def test_request_cap_failure_keeps_reference_without_staging(self):
        class Connector:
            def fetch_post(self, ref):
                session = requests.Session()
                for _ in range(4):
                    try: session.send(None)
                    except RuntimeError: pass
                return RawDoc('blog', 'https://example.test/post', raw_content='partial')
        with patch.object(requests.Session, 'send', return_value=None) as send:
            with self.assertRaises(ValueError): stage_one(self.queue, Connector(), lambda *_: True, lambda: None)
        self.assertEqual(send.call_count, 3)
        self.assertEqual(self.queue.conn.execute('SELECT count(*) FROM pending').fetchone()[0], 0)
        self.assertEqual(len(list(self.queue.revision_refs('blog'))), 1)


if __name__ == '__main__': unittest.main()
