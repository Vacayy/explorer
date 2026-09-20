import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from routers import spine_home


class HomeAiActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'activity.sqlite'
        with sqlite3.connect(self.path) as conn:
            conn.executescript('''
                CREATE TABLE narratives(topic TEXT, title TEXT, created_at TEXT, kind TEXT);
                CREATE TABLE reports(anchor_topic TEXT, title TEXT, created_at TEXT);
                CREATE TABLE scenarios(topic TEXT, question_id INTEGER, created_at TEXT);
                CREATE TABLE entities(id INTEGER, name TEXT, aliases TEXT);
                CREATE TABLE entity_digests(entity_id INTEGER, period TEXT, created_at TEXT);
                CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, source_type TEXT, title TEXT,
                    published_at TEXT, fetched_at TEXT, digest_status TEXT, markdown TEXT, raw_content TEXT);
                CREATE TABLE youtube_digest_jobs(doc_id INTEGER PRIMARY KEY, status TEXT, updated_at REAL);
                INSERT INTO narratives VALUES('시장', '시장 내러티브', datetime('now', '-1 day'), 'topic');
                INSERT INTO raw_documents VALUES
                    (1, 'youtube', '오래된 영상을 방금 요약', '2025-01-01', datetime('now', '-20 days'), 'ok', 'AI 정리본', '원본'),
                    (2, 'youtube', '기존 저장 요약', '2025-01-01', strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-2 days'), 'ok', '', 'AI 정리본'),
                    (3, 'youtube', '미생성', datetime('now'), datetime('now'), 'pending', '자막', '자막'),
                    (4, 'youtube', '실패', datetime('now'), datetime('now'), 'failed', '자막', '자막'),
                    (5, 'youtube', '오래된 요약의 자료 갱신', datetime('now'), datetime('now'), 'ok', 'AI 정리본', '원본'),
                    (6, 'youtube', '빈 요약', datetime('now'), datetime('now'), 'ok', '', ''),
                    (7, 'blog', '다른 소스', datetime('now'), datetime('now'), 'ok', '본문', '본문');
                INSERT INTO youtube_digest_jobs VALUES
                    (1, 'ok', unixepoch('now', '-1 hour')),
                    (3, 'generating', unixepoch('now')),
                    (4, 'failed', unixepoch('now')),
                    (5, 'ok', unixepoch('now', '-20 days'));
            ''')

    def read(self, *, limit=30):
        def connect():
            conn = sqlite3.connect(f'file:{self.path}?mode=ro', uri=True)
            conn.row_factory = sqlite3.Row
            return conn

        with patch.object(spine_home, 'get_connection', side_effect=connect):
            return spine_home.ai_activity(days=7, limit=limit)

    def test_completed_digests_use_generation_time_and_keep_legacy_summaries(self):
        items = self.read()
        self.assertEqual([(item.type, item.doc_id) for item in items],
                         [('youtube_digest', 1), ('narrative', None), ('youtube_digest', 2)])
        self.assertEqual(items[0].title, '오래된 영상을 방금 요약')
        self.assertEqual(items[0].created_at[10], ' ')
        self.assertEqual(items[2].created_at[10], ' ')

    def test_limit_is_applied_after_combining_all_activity_types(self):
        self.assertEqual([item.doc_id for item in self.read(limit=1)], [1])
        self.assertEqual([item.type for item in self.read(limit=2)], ['youtube_digest', 'narrative'])


if __name__ == '__main__':
    unittest.main()
