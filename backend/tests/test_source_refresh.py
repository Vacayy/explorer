"""소스 즉시 수집(D-199): 같은 소스 중복 시작 없음, 상태 전이, 실행 기록, 유튜브 채널 필터."""
import sqlite3
import threading
import time
import unittest
from unittest import mock

from pipeline import source_refresh


class FakeConnector:
    def __init__(self, kind, key):
        self.kind, self.key = kind, key


def wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class Start(unittest.TestCase):
    def setUp(self):
        source_refresh._STATE.clear()
        self.runs = []
        patcher = mock.patch("pipeline.ops.record_run", side_effect=lambda *a, **k: self.runs.append(a))
        patcher.start(); self.addCleanup(patcher.stop)
        flag = mock.patch("pipeline.ops.flag_enabled", return_value=True)
        flag.start(); self.addCleanup(flag.stop)

    def test_runs_in_background_and_records_stats(self):
        gate = threading.Event()

        def runner(connector):
            gate.wait(2)
            return {"refs": 1, "docs": 3, "new": 2, "updated": 1, "unchanged": 0}

        first = source_refresh.start("telegram", "chan", runner=runner, connector_factory=FakeConnector)
        self.assertEqual(first["status"], "running")
        again = source_refresh.start("telegram", "chan", runner=runner, connector_factory=FakeConnector)
        self.assertTrue(again["already_running"], "a running refresh is returned, not duplicated")
        gate.set()
        self.assertTrue(wait_until(lambda: source_refresh.status("telegram", "chan")["status"] == "done"))
        state = source_refresh.status("telegram", "chan")
        self.assertEqual((state["stats"]["new"], state["stats"]["updated"], state["stats"]["source"]), (2, 1, "telegram:chan"))
        self.assertTrue(state["finished_at"])
        self.assertEqual(self.runs[-1][:2], ("refresh_source", "ok"))
        self.assertIn("new 2", self.runs[-1][2])

    def test_error_is_kept_in_state_and_recorded(self):
        def runner(connector):
            raise RuntimeError("t.me unreachable")

        source_refresh.start("blog", "https://x", runner=runner, connector_factory=FakeConnector)
        self.assertTrue(wait_until(lambda: source_refresh.status("blog", "https://x")["status"] == "error"))
        self.assertIn("RuntimeError", source_refresh.status("blog", "https://x")["error"])
        self.assertEqual(self.runs[-1][1], "error")
        # 끝난 뒤에는 다시 시작할 수 있다
        self.assertFalse(source_refresh.start("blog", "https://x", runner=lambda c: {"refs": 0, "docs": 0, "new": 0, "updated": 0, "unchanged": 0},
                                              connector_factory=FakeConnector).get("already_running"))

    def test_admin_flag_off_is_skipped_not_run(self):
        with mock.patch("pipeline.ops.flag_enabled", return_value=False):
            called = []
            source_refresh.start("youtube", "UC1", runner=lambda c: called.append(1) or {}, connector_factory=FakeConnector)
            self.assertTrue(wait_until(lambda: source_refresh.status("youtube", "UC1")["status"] == "skipped"))
        self.assertEqual(called, [])

    def test_idle_and_unknown_kind(self):
        self.assertEqual(source_refresh.status("telegram", "nobody")["status"], "idle")
        with self.assertRaises(ValueError):
            source_refresh.start("rss", "x")

    def test_registered_checks_registry_table(self):
        conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE telegram_channels (channel_name TEXT)")
        conn.execute("INSERT INTO telegram_channels VALUES ('a')")
        self.assertTrue(source_refresh.registered(conn, "telegram", "a"))
        self.assertFalse(source_refresh.registered(conn, "telegram", "b"))


class YouTubeChannelFilter(unittest.TestCase):
    def test_channel_ids_ignore_active_flags_and_only_that_channel(self):
        from pipeline.connectors import youtube as yt
        conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE youtube_channels (channel_id TEXT PRIMARY KEY, title TEXT, is_active INTEGER, collect_enabled INTEGER);
            INSERT INTO youtube_channels VALUES ('UCa', 'A', 0, 0), ('UCb', 'B', 1, 1);
            CREATE TABLE raw_documents (source_type TEXT, source_id TEXT);
            INSERT INTO raw_documents VALUES ('youtube', 'UCa/seen1');
        """)
        class Keep:  # get_connection()이 돌려준 뒤 close()해도 메모리 DB가 살아 있게
            def __init__(self, inner): self._inner = inner
            def __getattr__(self, name): return getattr(self._inner, name)
            def close(self): pass
        conn = Keep(conn)
        feed = {"UCa": [{"yt_videoid": "seen1", "title": "old"}, {"yt_videoid": "new1", "title": "new", "published": "2026-09-23"}],
                "UCb": [{"yt_videoid": "b1", "title": "b"}]}

        class Resp:
            def __init__(self, cid): self.content = cid
        with mock.patch.object(yt, "get_connection", return_value=conn), \
             mock.patch.object(yt.requests, "get", side_effect=lambda url, **k: Resp(url.split("channel_id=")[-1])), \
             mock.patch.object(yt.feedparser, "parse", side_effect=lambda cid: mock.Mock(entries=feed[cid])):
            refs = yt.YouTubeConnector(channel_ids=["UCa"]).discover()
        self.assertEqual([r.key for r in refs], ["new1"], "seen videos skipped, other channels not touched, inactive flag ignored")
        self.assertEqual(refs[0].meta["channel_id"], "UCa")


if __name__ == "__main__":
    unittest.main()
