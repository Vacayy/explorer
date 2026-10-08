import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from pipeline import youtube_digest as service
from routers import spine_doc

class YouTubeDigestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.db'
        self.patches = [patch.object(m, 'get_connection', side_effect=self.connect) for m in (service, spine_doc)]
        for p in self.patches: p.start()
        c = self.connect()
        c.executescript(service.SCHEMA + '''
        CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,source_type TEXT,source_id TEXT,title TEXT,url TEXT,published_at TEXT,markdown TEXT,raw_content TEXT,digest_status TEXT,media_json TEXT);
        CREATE TABLE enrichments(id INTEGER PRIMARY KEY,doc_id INTEGER,summary TEXT,model TEXT,enriched_at TEXT);
        CREATE TABLE entity_links(doc_id INTEGER,entity_id INTEGER,link_type TEXT,confidence REAL);
        CREATE TABLE entities(id INTEGER,type TEXT,name TEXT,aliases TEXT);
        ''')
        for id, status, body in [(1,'pending','원본 자막😀' * 30),(2,'ok','## 기존 긴 정리본'),(3,'failed','다른 자막' * 30)]:
            c.execute('INSERT INTO raw_documents VALUES(?,?,?,?,?,?,?,?,?,?)', (id,'youtube',str(id),'영상','https://example.com','2026-09-10',body,body,status,None))
        c.executemany('INSERT INTO enrichments VALUES(?,?,?,?,?)', [(1,1,'옛 요약','test','2026-09-01'),(2,1,'최근 요약','test','2026-09-10')])
        c.commit();c.close()
    def tearDown(self):
        for p in self.patches: p.stop()
        self.tmp.cleanup()
    def connect(self):
        c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;return c
    def read(self,id):
        with patch('routers.spine_feed.resolve_channels',return_value={}): return spine_doc.get_document(id)
    def test_get_is_pure_and_returns_latest_short_summary(self):
        with patch('pipeline.connectors.youtube.digest_stored') as generate, patch.object(service,'queue') as queue:
            doc=self.read(1)
            generate.assert_not_called();queue.assert_not_called()
        self.assertEqual(doc.summary,'최근 요약')
        self.assertIsNone(doc.video_digest)
        self.assertTrue(doc.transcript.startswith('원본'))
    def test_legacy_digest_is_not_mislabeled_as_transcript(self):
        doc=self.read(2)
        self.assertEqual(doc.video_digest,'## 기존 긴 정리본')
        self.assertIsNone(doc.transcript)
        self.assertIsNone(service.queue(2)['token'])
    def test_duplicate_requests_share_job_and_preserve_original(self):
        first=service.queue(1)
        self.assertTrue(first['token']);self.assertIsNone(service.queue(1)['token'])
        c=self.connect();c.execute("UPDATE raw_documents SET markdown='## 새 정리본',raw_content='## 새 정리본',digest_status='ok' WHERE id=1");c.commit();c.close()
        doc=self.read(1)
        self.assertEqual(doc.video_digest,'## 새 정리본')
        self.assertTrue(doc.transcript.startswith('원본'))
    def test_failed_generation_can_retry_without_automatic_get_retry(self):
        job=service.queue(3)
        with patch('pipeline.connectors.youtube._digest_stored',return_value=False):
            self.assertFalse(service.execute(3,job['token']))
        doc=self.read(3)
        self.assertEqual(doc.digest_status,'failed');self.assertTrue(doc.digest_error)
        self.assertNotEqual(service.queue(3)['token'],job['token'])
    def test_exception_and_interrupted_job_are_visible(self):
        job=service.queue(1)
        with patch('pipeline.connectors.youtube._digest_stored',side_effect=RuntimeError('private message')):
            service.execute(1,job['token'])
        self.assertNotIn('private message',self.read(1).digest_error)
        job=service.queue(1)
        c=self.connect();c.execute('UPDATE youtube_digest_jobs SET updated_at=0');c.commit();c.close()
        self.assertEqual(self.read(1).digest_status,'interrupted')
        self.assertNotEqual(service.queue(1)['token'],job['token'])
    def test_http_only_enqueues_background_work(self):
        from fastapi import BackgroundTasks
        tasks=BackgroundTasks()
        with patch.object(service,'execute') as execute:
            result=spine_doc.generate_digest(1,tasks)
            execute.assert_not_called()
        self.assertEqual(result['status'],'generating');self.assertEqual(len(tasks.tasks),1)
        spine_doc.generate_digest(1,tasks)
        self.assertEqual(len(tasks.tasks),1)

    def test_auth_failure_does_not_repeat_slow_generation(self):
        from pipeline.connectors.youtube import digest_transcript
        from types import SimpleNamespace
        with patch('pipeline.enrich.llm_engine',return_value='claude-code'), patch('pipeline.enrich._claude_bin',return_value='claude'), patch('subprocess.run',return_value=SimpleNamespace(returncode=1,stdout='OAuth session expired',stderr='')) as run, patch('time.sleep') as sleep:
            self.assertIsNone(digest_transcript('test','자막' * 100))
            run.assert_called_once();sleep.assert_not_called()

    # 텔레그램 봇 영상 액션 — GET은 생성하지 않으므로 봇이 직접 작업을 돌려야 한다 (원본 자막이 그대로 나가던 버그)
    def bot(self, id):
        from pipeline import bot
        with patch('routers.spine_feed.resolve_channels', return_value={}): return bot._run_youtube(id)[0]
    def bot_ok(self, id):
        from pipeline import bot
        with patch('routers.spine_feed.resolve_channels', return_value={}): return bot._run_youtube(id)[1]
    def test_bot_generates_digest_instead_of_sending_transcript(self):
        def done(doc_id):
            c=self.connect();c.execute("UPDATE raw_documents SET markdown='## 봇 정리본',raw_content='## 봇 정리본',digest_status='ok' WHERE id=?",(doc_id,));c.commit();c.close()
            return True
        with patch('pipeline.connectors.youtube._digest_stored', side_effect=done) as generate:
            out=self.bot(1)
        generate.assert_called_once_with(1)
        self.assertIn('## 봇 정리본', out);self.assertNotIn('원본 자막', out)
    def test_bot_reports_failure_without_transcript(self):
        with patch('pipeline.connectors.youtube._digest_stored', return_value=False):
            out=self.bot(3)
        self.assertIn('정리본을 만들지 못했습니다', out);self.assertNotIn('다른 자막', out)
    def test_bot_reuses_existing_digest(self):
        with patch('pipeline.connectors.youtube._digest_stored') as generate:
            out=self.bot(2)
        generate.assert_not_called();self.assertIn('## 기존 긴 정리본', out)
    def test_bot_does_not_duplicate_running_job(self):
        service.queue(1)
        with patch('pipeline.connectors.youtube._digest_stored') as generate:
            out=self.bot(1)
        generate.assert_not_called();self.assertIn('정리 중', out);self.assertNotIn('원본 자막', out)
    def test_bot_short_transcript_message(self):
        c=self.connect();c.execute("INSERT INTO raw_documents VALUES(4,'youtube','4','짧은 영상','u','2026-09-10','짧음','짧음','pending',NULL)");c.commit();c.close()
        self.assertIn('자막이 충분하지 않습니다', self.bot(4))

    def test_bot_reports_success_flag(self):
        with patch('pipeline.connectors.youtube._digest_stored', return_value=False):
            self.assertFalse(self.bot_ok(3))
        self.assertTrue(self.bot_ok(2))

    def test_bot_action_outcome_is_recorded(self):
        import threading
        from pipeline import bot
        runs = []
        with patch.object(bot, '_post', return_value=10), patch.object(bot, '_edit', return_value=True), \
             patch('pipeline.ops.record_run', side_effect=lambda *a: runs.append(a)), \
             patch('routers.spine_feed.resolve_channels', return_value={}), \
             patch('pipeline.connectors.youtube._digest_stored', return_value=False), \
             patch.object(bot, 'get_connection', side_effect=self.connect):
            bot.start_action('y', '3', 'chat')
            for t in threading.enumerate():
                if t.name == 'tg-y-3': t.join()
        job, status, summary, _ms = runs[0]
        self.assertEqual((job, status), ('bot_y', 'error'))
        self.assertIn('y_3', summary); self.assertIn('전달 ok', summary); self.assertIn('정리본을 만들지 못했습니다', summary)

if __name__ == '__main__': unittest.main()
