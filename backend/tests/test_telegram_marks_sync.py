import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.telegram_marks_sync import GroupMarkConflict, GroupMarks


class Result:
    def __init__(self, rows=()): self.rows = list(rows)
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows


class FakePG:
    def __init__(self):
        self.rows = {}
        self.fail_insert = False
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def transaction(self): return self
    def execute(self, sql, params=()):
        if 'SELECT row_data' in sql:
            row = self.rows.get((params[0], int(params[1])))
            return Result([(row,)] if row else [])
        if 'SELECT 1 FROM legacy_supplement_tables' in sql:
            return Result([(1,)])
        if 'INSERT INTO legacy_supplement_rows' in sql:
            if self.fail_insert: raise RuntimeError('synthetic PG failure')
            data = params[0].obj
            self.rows[(data['channel'], data['msg_id'])] = data
        return Result()


class GroupMarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'work.db'
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE telegram_group_marks(channel TEXT,msg_id INTEGER,joins_prev INTEGER,"
                       "model TEXT,judged_at TEXT DEFAULT (datetime('now')),PRIMARY KEY(channel,msg_id))")
        self.pg = FakePG()
        self.marks = GroupMarks(lambda: self.pg, lambda: sqlite3.connect(self.path))
        self.guard = patch('pipeline.telegram_marks_sync._guard')
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_new_mark_is_idempotent_and_existing_decision_wins(self):
        self.assertIsNone(self.marks.get('synthetic', 1))
        self.assertTrue(self.marks.put('synthetic', 1, True, 'gap'))
        self.assertEqual(self.marks.get('synthetic', 1), {'joins_prev': True})
        self.assertTrue(self.marks.put('synthetic', 1, False, 'gap'))
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT joins_prev FROM telegram_group_marks').fetchone()[0], 1)

    def test_pg_failure_rolls_back_local_mark(self):
        self.pg.fail_insert = True
        with self.assertRaises(RuntimeError): self.marks.put('synthetic', 1, True, 'gap')
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM telegram_group_marks').fetchone()[0], 0)

    def test_existing_difference_stops_without_replacing_either(self):
        self.marks.put('synthetic', 1, True, 'gap')
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE telegram_group_marks SET joins_prev=0')
        with self.assertRaises(GroupMarkConflict): self.marks.get('synthetic', 1)
        with self.assertRaises(GroupMarkConflict): self.marks.put('synthetic', 1, False, 'gap')
        self.assertEqual(self.pg.rows[('synthetic', 1)]['joins_prev'], 1)

    def test_local_commit_failure_is_detected_before_reuse(self):
        class FailCommit:
            def __init__(self, path): self.db = sqlite3.connect(path)
            def execute(self, *args): return self.db.execute(*args)
            def commit(self): raise OSError('synthetic local failure')
            def rollback(self): self.db.rollback()
            def close(self): self.db.close()
        failing = GroupMarks(lambda: self.pg, lambda: FailCommit(self.path))
        with self.assertRaises(OSError): failing.put('synthetic', 1, True, 'gap')
        with self.assertRaises(GroupMarkConflict): self.marks.get('synthetic', 1)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM telegram_group_marks').fetchone()[0], 0)

    def test_gap_fallback_stages_text_and_keeps_original_page(self):
        from pipeline.base import SourceRef
        from pipeline.connectors.telegram import TelegramConnector
        from pipeline.feed_backlog import FeedBacklog, fetch_pending_reference
        messages = [{'message_id': str(n), 'content': 'synthetic', 'date': f'2026-01-01T00:0{n}:00Z',
                     'link': 'https://example.test', 'images': ['https://example.test/image']} for n in (1, 2)]
        ref = SourceRef('page', meta={'channel': 'synthetic', 'messages': messages})
        connector = TelegramConnector(mark_store=self.marks, judge=lambda *_: None,
                                      image_reader=lambda items, **kwargs: {}, image_finder=lambda *_: [])
        queue = FeedBacklog(Path(self.tmp.name) / 'queue.db')
        queue.enqueue_ref('telegram', 'synthetic', ref)
        self.assertEqual(fetch_pending_reference(queue, {'telegram': connector}, retain_names={'telegram'}), 1)
        self.assertIsNotNone(queue.next())
        self.assertIsNone(queue.next_pending_ref())
        self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending_refs WHERE revision_pending=1').fetchone()[0], 1)
        self.assertEqual(len(self.pg.rows), 1)
        queue.close()


if __name__ == '__main__': unittest.main()
