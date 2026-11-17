import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pipeline.base import RawDoc
from pipeline.feed_backlog import FeedBacklog
from pipeline import feed_image_trial


class FeedImageTrialTest(unittest.TestCase):
    def test_image_result_is_staged_without_removing_the_document(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = FeedBacklog(Path(directory) / 'queue.sqlite')
            queue.enqueue('blog', 'feed', RawDoc('blog', 'id', kind='html',
                                                 raw_content='<p>example</p><img src="https://example.test/a.png">'))
            seq = queue.next()[0]
            queue.defer_revision(seq, reason='analysis')
            marker = Mock()
            with patch.object(feed_image_trial.image_reading, '_load', return_value=(b'image', 'png')), \
                 patch.object(feed_image_trial.image_reading, '_call', return_value={'kind': 'chart', 'model': 'codex-exec/test'}):
                result = feed_image_trial.stage_one(queue, marker)
            marker.assert_called_once()
            self.assertEqual(result['image_staged'], 1)
            self.assertEqual(result['image_valid'], 1)
            self.assertEqual(queue.conn.execute('SELECT status FROM staged_image_results').fetchone()[0], 'ready')
            self.assertEqual(queue.conn.execute("SELECT count(*) FROM pending WHERE defer_reason='analysis'").fetchone()[0], 1)
            queue.close()
