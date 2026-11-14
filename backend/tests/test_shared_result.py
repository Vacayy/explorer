"""같은 계산 함께 쓰기 (API 성능 A단계 ⑦, services/shared_result).

- 같은 키를 동시에 부르면 한 번만 계산한다.
- 그 사이 다른 연결이 DB에 커밋하면 다음 요청은 다시 계산한다(묵은 값 없음). TTL이 지나도 다시 계산한다.
- /regimes/state와 /regimes/commentary가 동시에 와도 era.get_state()는 한 번.
"""
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import database
from services import shared_result


class SharedTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "t.db"
        c = sqlite3.connect(self.path)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE t (x)")
        c.commit()
        c.close()
        patch.object(database, "DB_PATH", self.path).start()
        patch.object(shared_result, "_entries", {}).start()
        self.addCleanup(patch.stopall)
        self.calls = 0

    def compute(self, delay=0.0):
        def run():
            self.calls += 1
            time.sleep(delay)
            return {"n": self.calls}
        return run

    def write(self):
        c = sqlite3.connect(self.path)
        c.execute("INSERT INTO t VALUES (1)")
        c.commit()
        c.close()

    def test_concurrent_same_key_computes_once(self):
        out = []
        threads = [threading.Thread(target=lambda: out.append(shared_result.shared(("k",), self.compute(0.3))))
                   for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(self.calls, 1)
        self.assertEqual(out, [{"n": 1}] * 4)

    def test_commit_from_other_connection_recomputes(self):
        self.assertEqual(shared_result.shared(("k",), self.compute()), {"n": 1})
        self.assertEqual(shared_result.shared(("k",), self.compute()), {"n": 1})
        self.write()
        self.assertEqual(shared_result.shared(("k",), self.compute()), {"n": 2})

    def test_ttl_and_keys(self):
        shared_result.shared(("a",), self.compute())
        shared_result.shared(("b",), self.compute())
        self.assertEqual(self.calls, 2)
        self.assertEqual(shared_result.shared(("a",), self.compute(), ttl=0), {"n": 3})


class RegimesTests(unittest.TestCase):
    def test_state_and_commentary_share_one_get_state(self):
        from pipeline import era, era_commentary
        from routers import spine_regimes
        calls = []

        def fake_state():
            calls.append(1)
            time.sleep(0.3)
            return {"state": {"available": False}, "meaning": {}, "temperature": {}, "premises": [], "latest_memos": [],
                    "generated_at": "x"}
        with patch.object(era, "get_state", fake_state), patch.object(era_commentary, "get_state", fake_state), \
                patch.object(shared_result, "_entries", {}), \
                patch.object(shared_result, "_db_state", return_value=("db", 1)), \
                patch("pipeline.pricing_ledger.brief", return_value={"as_of": None, "summary": None, "claims": []}):
            got = {}
            threads = [threading.Thread(target=lambda: got.setdefault("state", spine_regimes.state())),
                       threading.Thread(target=lambda: got.setdefault("inputs", era_commentary._inputs()))]
            [t.start() for t in threads]
            [t.join() for t in threads]
        self.assertEqual(len(calls), 1)
        self.assertEqual(got["state"]["generated_at"], "x")
        self.assertEqual(got["inputs"]["premises"], [])


if __name__ == "__main__":
    unittest.main()
