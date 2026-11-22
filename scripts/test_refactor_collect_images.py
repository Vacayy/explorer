"""Image recovery job ('images'): its own hold, never while the feed is held, after the chain only when enabled."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import refactor_collect_engine as engine
import refactor_collect_job as job
import refactor_collect_scheduler as scheduler

FEED_ENV = {'COLLECT_CHAIN_INTAKE_ONLY': '1', 'COLLECT_FEED_WORK_VOLUME': 'explorer-refactor-collect-feed-test'}


class ImageRecoveryJobTests(unittest.TestCase):
    def holds(self, directory):
        return (patch.object(scheduler, 'HOLD', Path(directory) / 'global'),
                patch.object(scheduler, 'FEED_HOLD', Path(directory) / 'feed'),
                patch.object(scheduler, 'IMAGES_HOLD', Path(directory) / 'images'))

    def test_registered_as_a_table_step_with_two_attempts_per_reading(self):
        argv, record = job.job_argv('images')
        self.assertEqual((argv[0], record), ('scripts/recover_images.py', 'image_recovery'))
        self.assertIn('images', job.CHAIN_TABLE_STEPS)
        self.assertNotIn('images', job.COMPUTE_JOBS)
        self.assertEqual(job.TABLE_MODEL_CAPS['images'], 2 * int(argv[argv.index('--images') + 1]))
        scheduler.check_enabled({'images'})

    def test_failure_holds_only_itself(self):
        with TemporaryDirectory() as directory:
            hold, feed, images = self.holds(directory)
            with hold, feed, images, patch.dict(os.environ, FEED_ENV), patch.object(scheduler, '_run_one', return_value=False):
                self.assertFalse(scheduler.run_job('images', lambda *_: None))
                self.assertTrue(scheduler.IMAGES_HOLD.exists())
                self.assertFalse(scheduler.FEED_HOLD.exists())
                self.assertFalse(scheduler.HOLD.exists())

    def test_does_not_run_while_the_feed_is_held(self):
        with TemporaryDirectory() as directory:
            hold, feed, images = self.holds(directory)
            with hold, feed, images, patch.dict(os.environ, FEED_ENV), patch.object(scheduler, '_run_one') as run_one:
                scheduler.FEED_HOLD.write_text('chain held\n')
                self.assertFalse(scheduler.run_job('images', lambda *_: None))
                run_one.assert_not_called()
                self.assertFalse(scheduler.IMAGES_HOLD.exists())

    def test_runs_after_the_intake_only_when_enabled_and_never_changes_its_outcome(self):
        with TemporaryDirectory() as directory:
            hold, feed, images = self.holds(directory)
            ran = []
            with hold, feed, images, patch.dict(os.environ, FEED_ENV), \
                    patch.object(scheduler, '_run_one', side_effect=lambda label, log: ran.append(label) or label == 'chain'):
                self.assertTrue(scheduler.run_job('chain', lambda *_: None))
                self.assertEqual(ran, ['chain'])
                with patch.dict(os.environ, {'COLLECT_CHAIN_IMAGES': '1'}):
                    self.assertTrue(scheduler.run_job('chain', lambda *_: None))   # images failed; the chain did not
                self.assertEqual(ran, ['chain', 'chain', 'images'])
                self.assertTrue(scheduler.IMAGES_HOLD.exists())
                self.assertFalse(scheduler.FEED_HOLD.exists())

    def test_uses_the_feed_collector_file(self):
        self.assertIn("'images'", Path(engine.__file__).read_text().split('volume = FEED_VOLUME if job in', 1)[1].split('\n', 1)[0])
        self.assertIn('COLLECT_IMAGE_RECOVERY_IMAGES', engine.FORWARDED)
        self.assertIn('images', scheduler.JOB_HOST_CAPS)


if __name__ == '__main__':
    unittest.main()
