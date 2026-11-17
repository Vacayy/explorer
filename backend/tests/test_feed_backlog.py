import tempfile
import unittest
from pathlib import Path

from pipeline.base import RawDoc
from pipeline.feed_backlog import FeedBacklog


class FeedBacklogTest(unittest.TestCase):
    def test_rejects_missing_identity_and_nonprivate_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pending.sqlite'
            queue = FeedBacklog(path)
            with self.assertRaises(ValueError):
                queue.enqueue('test', 'ref', RawDoc('test', ''))
            queue.close()
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                FeedBacklog(path)

    def test_durable_fair_delivery_and_latest_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pending.sqlite'
            queue = FeedBacklog(path)
            for lane, ident in [('a', '1'), ('a', '2'), ('a', '3'), ('b', '4'), ('c', '5')]:
                queue.enqueue('blog', lane, RawDoc('blog', ident, raw_content='old'))
            queue.enqueue('blog', 'a', RawDoc('blog', '1', raw_content='new'))
            queue.close()
            queue = FeedBacklog(path)
            first = []
            for _ in range(3):
                seq, doc = queue.next()
                first.append(doc.source_id)
                if doc.source_id == '1':
                    self.assertEqual(doc.raw_content, 'new')
                queue.acknowledge(seq)
            self.assertEqual(set(first), {'1', '4', '5'})
            self.assertIsNotNone(queue.next())
            queue.close()

    def test_unacknowledged_document_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pending.sqlite'
            queue = FeedBacklog(path)
            queue.enqueue('test', 'ref', RawDoc('test', 'id'))
            seq, _ = queue.next()
            queue.close()
            queue = FeedBacklog(path)
            self.assertEqual(queue.next()[0], seq)
            queue.acknowledge(seq)
            self.assertIsNone(queue.next())
            queue.close()
