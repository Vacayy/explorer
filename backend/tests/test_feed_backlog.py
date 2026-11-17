import tempfile
import unittest
from pathlib import Path

from pipeline.base import RawDoc, SourceRef
from pipeline.feed_backlog import FeedBacklog, fetch_pending_reference, stage_one_reference


class FeedBacklogTest(unittest.TestCase):
    def test_batch_rotates_source_lanes_without_acknowledging(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = FeedBacklog(Path(directory) / 'pending.sqlite')
            for lane, ident in [('a', '1'), ('a', '2'), ('b', '3'), ('b', '4')]:
                queue.enqueue('blog', lane, RawDoc('blog', ident))
            batch = queue.batch(allowed={'blog'}, limit=2)
            self.assertEqual(len(batch), 2)
            self.assertIn(batch[0][2].source_id, {'1', '3'})
            self.assertEqual({x[2].source_id for x in batch}, {'1', '3'})
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending').fetchone()[0], 4)
            queue.close()
    def test_existing_revision_payload_is_retained_but_does_not_block_new_docs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pending.sqlite'
            queue = FeedBacklog(path)
            queue.enqueue('telegram', 'channel', RawDoc('telegram', 'existing', raw_content='new version'))
            seq = queue.next()[0]
            queue.defer_revision(seq)
            queue.enqueue('telegram', 'channel', RawDoc('telegram', 'new', raw_content='body'))
            queue.close()
            queue = FeedBacklog(path)
            self.assertEqual(queue.next()[2].source_id, 'new')
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending WHERE revision_pending=1').fetchone()[0], 1)
            queue.close()

    def test_discovered_revision_reference_is_retained_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = FeedBacklog(Path(directory) / 'pending.sqlite')
            queue.enqueue_ref('blog', 'feed', SourceRef('old-version'), revision_pending=True)
            queue.enqueue_ref('blog', 'feed', SourceRef('new-document'))
            self.assertEqual(queue.next_pending_ref()[2].key, 'new-document')
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending_refs WHERE revision_pending=1').fetchone()[0], 1)
            queue.close()
    def test_disabled_sources_remain_queued_without_blocking_enabled_source(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = FeedBacklog(Path(directory) / 'pending.sqlite')
            queue.enqueue_ref('youtube', 'channel', SourceRef('video'))
            queue.enqueue_ref('blog', 'feed', SourceRef('post'))
            queue.enqueue('youtube', 'channel', RawDoc('youtube', 'video'))
            queue.enqueue('blog', 'feed', RawDoc('blog', 'post'))
            self.assertEqual(queue.next_pending_ref(allowed={'blog'})[1], 'blog')
            self.assertEqual(queue.next(allowed={'blog'})[1], 'blog')
            self.assertEqual(queue.next_pending_ref(allowed={'youtube'})[1], 'youtube')
            self.assertEqual(queue.next(allowed={'youtube'})[1], 'youtube')
            self.assertIsNone(queue.next(allowed=set()))
            queue.close()
    def test_reference_ack_only_after_documents_are_durable(self):
        class Connector:
            def fetch(self, ref):
                yield RawDoc('youtube', ref.key)
                raise RuntimeError('interrupted after one document')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pending.sqlite'
            queue = FeedBacklog(path)
            queue.enqueue_ref('youtube', 'channel', SourceRef('video'))
            with self.assertRaises(RuntimeError):
                fetch_pending_reference(queue, {'youtube': Connector()})
            queue.close()
            queue = FeedBacklog(path)
            self.assertEqual(queue.next_pending_ref()[2].key, 'video')
            self.assertEqual(queue.next()[2].source_id, 'video')
            queue.close()
    def test_discovered_refs_survive_restart_and_empty_fetch_can_yield(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pending.sqlite'
            queue = FeedBacklog(path)
            queue.enqueue_ref('youtube', 'channel-a', SourceRef('first', {'channel': 'a'}))
            queue.enqueue_ref('youtube', 'channel-b', SourceRef('second', {'channel': 'b'}))
            first = queue.next_pending_ref()
            queue.defer_ref(first[0])
            second = queue.next_pending_ref()
            self.assertNotEqual(first[2].key, second[2].key)
            queue.close()
            queue = FeedBacklog(path)
            self.assertEqual(queue.next_pending_ref()[2].meta, second[2].meta)
            queue.acknowledge_ref(second[0])
            self.assertEqual(queue.next_pending_ref()[2].key, first[2].key)
            queue.close()

    def test_failed_reference_does_not_starve_same_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = FeedBacklog(Path(directory) / 'pending.sqlite')
            queue.enqueue_ref('youtube', 'channel', SourceRef('first'))
            queue.enqueue_ref('youtube', 'channel', SourceRef('second'))
            first = queue.next_pending_ref()
            queue.defer_ref(first[0])
            self.assertEqual(queue.next_pending_ref()[2].key, 'second')
            queue.close()
    def test_intent_survives_restart_and_requires_confirmed_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pending.sqlite'
            queue = FeedBacklog(path)
            doc = RawDoc('blog', 'id')
            queue.enqueue('blog', 'ref', doc)
            seq = queue.next()[0]
            token = queue.begin_publication(seq)
            with self.assertRaises(ValueError):
                queue.acknowledge(seq)
            with self.assertRaises(ValueError):
                queue.enqueue('blog', 'ref', doc)
            queue.close()
            queue = FeedBacklog(path)
            self.assertEqual(queue.intent(), (token, seq))
            with self.assertRaises(ValueError):
                queue.finish_publication(token, receipt_confirmed=False)
            with self.assertRaises(ValueError):
                queue.finish_publication('wrong', receipt_confirmed=True)
            self.assertEqual(queue.next()[0], seq)
            queue.finish_publication(token, receipt_confirmed=True)
            self.assertIsNone(queue.intent())
            self.assertIsNone(queue.next())
            queue.close()
    def test_partial_fetch_is_durable_and_does_not_advance(self):
        class Connector:
            def discover(self):
                return [SourceRef('a'), SourceRef('b')]

            def fetch(self, ref):
                yield RawDoc('blog', ref.key)
                raise RuntimeError('simulated interruption')

        with tempfile.TemporaryDirectory() as directory:
            queue = FeedBacklog(Path(directory) / 'pending.sqlite')
            first = queue.next_ref('blog', Connector().discover()).key
            with self.assertRaises(RuntimeError):
                stage_one_reference(queue, 'blog', Connector())
            self.assertEqual(queue.next_ref('blog', Connector().discover()).key, first)
            self.assertEqual(queue.next()[2].source_id, first)
            queue.close()
    def test_source_cursor_rotates_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pending.sqlite'
            refs = [SourceRef('a'), SourceRef('b'), SourceRef('c')]
            queue = FeedBacklog(path)
            selected = []
            for _ in refs:
                ref = queue.next_ref('blog', refs)
                selected.append(ref.key)
                queue.advance_ref('blog', ref)
            queue.close()
            queue = FeedBacklog(path)
            self.assertEqual(len(set(selected)), 3)
            self.assertEqual(queue.next_ref('blog', refs).key, selected[0])
            self.assertEqual(queue.next_ref('note', refs).key, selected[0])
            self.assertIsNone(queue.next_ref('blog', []))
            queue.close()
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
                seq, connector, doc = queue.next()
                self.assertEqual(connector, 'blog')
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
            seq, _, _ = queue.next()
            queue.close()
            queue = FeedBacklog(path)
            self.assertEqual(queue.next()[0], seq)
            queue.acknowledge(seq)
            self.assertIsNone(queue.next())
            queue.close()
