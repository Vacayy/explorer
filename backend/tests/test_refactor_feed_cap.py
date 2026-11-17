import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import refactor_collect_trial as trial
import refactor_collect_job as job
from pipeline import postgres_collected_documents_fixture as documents
from pipeline import llm


class FeedCapTest(unittest.TestCase):
    def test_model_cap_blocks_extra_call(self):
        with patch.object(llm, '_execute', return_value=None) as original:
            refused = job._cap_table_model_calls(5)
            for _ in range(5):
                llm._execute()
            with self.assertRaises(RuntimeError):
                llm._execute()
            self.assertEqual(original.call_count, 5)
            self.assertEqual(len(refused), 1)

    def test_cap_is_checked_before_any_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / 'work.db'
            with sqlite3.connect(work) as conn:
                conn.execute('CREATE TABLE raw_documents (id INTEGER, source_type TEXT, source_id TEXT)')
            def refuse():
                raise trial.HeldBack('cap')
            with patch.object(trial, 'WORK', work), patch.object(trial, '_published_floors', return_value={}), \
                 patch.object(documents, 'publish') as publish:
                with self.assertRaises(trial.HeldBack):
                    trial.run_documents(None, [], 5, before_publish=refuse)
                publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
