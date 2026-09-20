"""Search threads: a run, its ancestors and every descendant of the root (D-184)."""
import tempfile
import unittest
from pathlib import Path

from pipeline.market_analysis.store import RunStore


class ThreadTests(unittest.TestCase):
    def test_thread_collects_root_and_descendants_oldest_first(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(Path(directory).resolve())
            root, _ = store.create({"question": "A", "request_key": "k1234567"})
            child, _ = store.create({"question": "B", "request_key": "k2345678", "parent_run_id": root["id"]})
            grand, _ = store.create({"question": "C", "request_key": "k3456789", "parent_run_id": child["id"]})
            # Lineage arrives later from the planner; the request already names the parent.
            store.mutate(child["id"], lambda s: s.update(lineage={"parent_run_id": root["id"], "changes": []}))
            other, _ = store.create({"question": "D", "request_key": "k4567890"})
            thread = store.thread(grand["id"])
            self.assertEqual(thread["root_id"], root["id"])
            self.assertEqual([i["id"] for i in thread["items"]], [root["id"], child["id"], grand["id"]])
            self.assertEqual([i["parent_run_id"] for i in thread["items"]], [None, root["id"], child["id"]])
            self.assertNotIn("_request", thread["items"][0])
            self.assertEqual(store.thread(root["id"])["items"][-1]["id"], grand["id"])
            self.assertEqual([i["id"] for i in store.thread(other["id"])["items"]], [other["id"]])


if __name__ == "__main__":
    unittest.main()
