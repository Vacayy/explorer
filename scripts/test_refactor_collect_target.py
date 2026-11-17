"""Collection target guard: live requires explicit opt-in and exact API schema."""
import os
import sqlite3
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import refactor_collect_trial as trial
import refactor_collect_scheduler as scheduler
import refactor_collect_engine as engine
import refactor_collect_job as job
import refactor_feed_recover as recover
import refactor_feed_sync as feed_sync
import refactor_feed_refresh as feed_refresh


class CollectionTargetTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(job, '_mark_identical_feed_revisions', return_value=0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_image_trial_without_candidate_does_not_block_future_feed(self):
        from pipeline import image_reading
        with TemporaryDirectory() as directory:
            path, marker = Path(directory) / 'queue', Path(directory) / 'image-marker'
            marker.write_text('feed-image-trial-v1\n')
            marker.chmod(0o600)
            with patch.dict(os.environ, {'COLLECT_FEED_KEYWORD_ONLY': '0', 'COLLECT_FEED_STRICT_IMAGES': '1'}), \
                 patch.object(job, 'MAX_MODEL_CALLS', 2), patch.object(image_reading, 'read_images'):
                result = job.run_minimal_blog(None, object(), queue_path=path, image_marker=marker)
            self.assertEqual(result['image_staged'], 0)
            self.assertFalse(marker.exists())

    def test_batch_model_results_are_applied_to_their_staged_documents(self):
        from pipeline import enrich, feed_enrichment, image_reading
        from pipeline.base import RawDoc
        from pipeline.feed_backlog import FeedBacklog
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'queue.sqlite'
            marker = Path(directory) / 'batch-marker'
            marker.write_text('feed-batch-trial-v1\n')
            marker.chmod(0o600)
            queue = FeedBacklog(path)
            queue.enqueue('blog', 'feed', RawDoc('blog', 'a', title='a', raw_content='first'))
            queue.enqueue('blog', 'feed', RawDoc('blog', 'b', title='b', raw_content='second'))
            queue.close()
            applied = []

            def run_docs(_pg, connectors, cap, before_publish):
                for doc in connectors[0].fetch(None):
                    applied.append(enrich.enrich(doc.title, doc.markdown)['summary'])
                before_publish()
                return {'counts': {'new': 2}, 'stats': {}, 'published': [1, 2]}

            with patch.dict(os.environ, {'COLLECT_FEED_BATCH_MODEL': '0', 'COLLECT_FEED_STRICT_IMAGES': '1',
                                         'COLLECT_FEED_KEYWORD_ONLY': '0'}), \
                 patch.object(job, 'MAX_NEW_DOCS', 5), patch.object(job, 'MAX_MODEL_CALLS', 2), \
                 patch.object(job, '_feed_document_known', return_value=False), \
                 patch.object(image_reading, 'read_images'), \
                 patch.object(feed_enrichment, 'enrich_documents', return_value=[{'summary': 'one'}, {'summary': 'two'}]), \
                 patch.object(trial, 'run_documents', side_effect=run_docs):
                job.run_minimal_blog(None, object(), queue_path=path, batch_marker=marker)
            self.assertEqual(set(applied), {'one', 'two'})
            self.assertFalse(marker.exists())
            queue = FeedBacklog(path)
            self.assertIsNone(queue.next())
            queue.close()

    def test_model_budget_holds_under_parallel_engine_attempts(self):
        from concurrent.futures import ThreadPoolExecutor
        from pipeline import llm
        attempts = []
        with patch.object(llm, '_run_claude_code'), patch.object(llm, '_run_codex'), \
             patch.object(llm, '_run_api', side_effect=lambda: attempts.append(1)):
            job._cap_table_model_calls(3)
            def invoke(_):
                try:
                    llm._run_api()
                except trial.Aborted:
                    pass
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(invoke, range(30)))
        self.assertEqual(len(attempts), 3)
    def test_group_mark_sync_appends_without_overwriting_or_dropping(self):
        a, b = sqlite3.connect(':memory:'), sqlite3.connect(':memory:')
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        for db in (a, b):
            db.execute('CREATE TABLE telegram_group_marks(channel TEXT,msg_id INTEGER,joins_prev INTEGER,model TEXT,judged_at TEXT,PRIMARY KEY(channel,msg_id))')
            db.execute("INSERT INTO telegram_group_marks VALUES ('c',1,0,'gap','t')")
            db.commit()
        a.execute("INSERT INTO telegram_group_marks VALUES ('c',2,1,'gap','t')")
        self.assertEqual(feed_sync.append_group_marks(a, b), 1)
        b.commit()
        self.assertEqual(b.execute('SELECT count(*) FROM telegram_group_marks').fetchone()[0], 2)
        a.execute("UPDATE telegram_group_marks SET joins_prev=1 WHERE msg_id=1")
        with self.assertRaises(ValueError):
            feed_sync.append_group_marks(a, b)
        self.assertEqual(b.execute('SELECT joins_prev FROM telegram_group_marks WHERE msg_id=1').fetchone()[0], 0)
        a.execute('DELETE FROM telegram_group_marks WHERE msg_id=2')
        a.execute('UPDATE telegram_group_marks SET joins_prev=0 WHERE msg_id=1')
        with self.assertRaises(ValueError):
            feed_sync.append_group_marks(a, b)
    def test_mark_only_feed_sync_commits_and_conflict_rolls_back(self):
        with TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ('source', 'target')]
            for path in paths:
                with sqlite3.connect(path) as db:
                    db.executescript('''
                        CREATE TABLE raw_documents(id INTEGER PRIMARY KEY);
                        CREATE TABLE enrichments(id INTEGER PRIMARY KEY);
                        CREATE TABLE entity_links(id INTEGER PRIMARY KEY);
                        CREATE TABLE entities(id INTEGER PRIMARY KEY);
                        CREATE TABLE entity_keywords(id INTEGER PRIMARY KEY);
                        CREATE TABLE entity_relations(id INTEGER PRIMARY KEY);
                        CREATE TABLE candidate_publish_floor(name TEXT PRIMARY KEY,value INTEGER);
                        INSERT INTO candidate_publish_floor VALUES ('document_floor',0),('entity_floor',0),('keyword_floor',0),('relation_floor',0);
                        CREATE TABLE telegram_group_marks(channel TEXT,msg_id INTEGER,joins_prev INTEGER,model TEXT,judged_at TEXT,PRIMARY KEY(channel,msg_id));
                    ''')
            with sqlite3.connect(paths[0]) as db:
                db.execute("INSERT INTO telegram_group_marks VALUES ('c',1,1,'gap','t')")
            feed_sync.sync(*paths, allow_noop=True)
            with sqlite3.connect(paths[1]) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM telegram_group_marks').fetchone()[0], 1)
            with sqlite3.connect(paths[0]) as db:
                db.execute("UPDATE telegram_group_marks SET joins_prev=0")
                db.execute("INSERT INTO telegram_group_marks VALUES ('c',2,1,'gap','t')")
            with self.assertRaises(ValueError): feed_sync.sync(*paths, allow_noop=True)
            with sqlite3.connect(paths[1]) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM telegram_group_marks').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT joins_prev FROM telegram_group_marks').fetchone()[0], 1)
    def test_persistent_batch_flag_keeps_five_documents_on_model_failure(self):
        from pipeline import feed_enrichment, image_reading
        from pipeline.base import RawDoc
        from pipeline.feed_backlog import FeedBacklog
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path, flag = root / 'queue.sqlite', root / 'enabled'
            flag.write_text('feed-batch-enabled-v1\n')
            flag.chmod(0o600)
            queue = FeedBacklog(path)
            for n in range(5):
                queue.enqueue('blog', 'feed', RawDoc('blog', str(n), title='test', raw_content='body'))
            queue.close()
            with patch.dict(os.environ, {'COLLECT_FEED_BATCH_MODEL': '0', 'COLLECT_FEED_STRICT_IMAGES': '1',
                                         'COLLECT_FEED_KEYWORD_ONLY': '0'}), \
                 patch.object(job, 'MAX_NEW_DOCS', 1), patch.object(job, 'MAX_MODEL_CALLS', 2), \
                 patch.object(job, '_feed_document_known', return_value=False), \
                 patch.object(image_reading, 'read_images'), \
                 patch.object(feed_enrichment, 'enrich_documents', side_effect=ValueError('synthetic')) as enrich, \
                 patch.object(trial, 'run_documents') as publish:
                with self.assertRaises(trial.HeldBack):
                    job.run_minimal_blog(None, object(), queue_path=path, batch_enabled=flag)
            self.assertEqual(len(enrich.call_args.args[0]), 5)
            publish.assert_not_called()
            self.assertTrue(flag.exists())
            queue = FeedBacklog(path)
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending').fetchone()[0], 5)
            queue.close()
    def test_batch_flag_rejects_unrecognized_or_insecure_file(self):
        with TemporaryDirectory() as directory:
            flag = Path(directory) / 'enabled'
            flag.write_text('not-the-expected-flag\n')
            flag.chmod(0o600)
            with self.assertRaises(ValueError):
                job.run_minimal_blog(None, object(), queue_path=Path(directory) / 'queue', batch_enabled=flag)
            flag.write_text('feed-batch-enabled-v1\n')
            flag.chmod(0o644)
            with self.assertRaises(ValueError):
                job.run_minimal_blog(None, object(), queue_path=Path(directory) / 'queue', batch_enabled=flag)
    def test_telegram_trial_rejects_unrecognized_flag(self):
        with TemporaryDirectory() as directory:
            flag = Path(directory) / 'telegram-trial'
            flag.write_text('unexpected\n'); flag.chmod(0o600)
            with self.assertRaises(ValueError):
                job.run_minimal_blog(None, object(), queue_path=Path(directory) / 'queue', telegram_trial=flag)
    def test_revision_trial_stages_one_snapshot_without_publishing(self):
        from pipeline.base import RawDoc, SourceRef
        from pipeline.feed_backlog import FeedBacklog
        class Blog:
            def discover(self): return []
            def fetch_post(self, ref): return RawDoc('blog', 'https://example.test/post', raw_content='synthetic')
        with TemporaryDirectory() as directory:
            root = Path(directory); path = root / 'queue'; flag = root / 'revision-trial'
            flag.write_text('feed-blog-revision-trial-v1\n'); flag.chmod(0o600)
            queue = FeedBacklog(path)
            queue.enqueue_ref('blog', 'feed', SourceRef('ref', meta={'post': {'url': 'https://example.test/post', 'content': 'rss'}}), revision_pending=True)
            queue.close()
            with patch.object(job, '_feed_document_known', return_value=True), patch.object(job, '_feed_blog_rss_differs', return_value=True), \
                 patch.object(trial, 'run_documents') as publish:
                result = job.run_minimal_blog(None, Blog(), queue_path=path, revision_trial=flag)
            self.assertEqual(result['revision_snapshot'], 1)
            self.assertEqual(result['published'], 0)
            self.assertFalse(flag.exists())
            publish.assert_not_called()
            queue = FeedBacklog(path)
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending WHERE revision_pending=1').fetchone()[0], 1)
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending_refs WHERE revision_pending=1').fetchone()[0], 1)
            queue.close()
    def test_revision_source_unavailable_does_not_stop_other_feed_work(self):
        from pipeline.base import SourceRef
        from pipeline.feed_backlog import FeedBacklog
        class Blog:
            def discover(self): return []
            def fetch_post(self, ref):
                from pipeline.base import RawDoc
                return RawDoc('blog', 'https://example.test/post', raw_content='')
        with TemporaryDirectory() as directory:
            root = Path(directory); path = root / 'queue'; flag = root / 'revision-trial'
            flag.write_text('feed-blog-revision-trial-v1\n'); flag.chmod(0o600)
            queue = FeedBacklog(path)
            queue.enqueue_ref('blog', 'feed', SourceRef('ref', meta={'post': {'url': 'https://example.test/post', 'content': 'rss'}}), revision_pending=True)
            queue.close()
            with patch.object(job, '_feed_document_known', return_value=True), patch.object(job, '_feed_blog_rss_differs', return_value=True):
                result = job.run_minimal_blog(None, Blog(), queue_path=path, revision_trial=flag)
            self.assertEqual(result['revision_error'], 'source_unavailable')
            self.assertEqual(result['published'], 0)
            self.assertFalse(flag.exists())
            queue = FeedBacklog(path)
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending_refs WHERE revision_pending=1').fetchone()[0], 1)
            queue.close()
    def test_telegram_enable_flag_rejects_insecure_file(self):
        with TemporaryDirectory() as directory:
            flag = Path(directory) / 'telegram-enabled'
            flag.write_text('feed-telegram-fallback-enabled-v1\n'); flag.chmod(0o644)
            with self.assertRaises(ValueError):
                job.run_minimal_blog(None, object(), queue_path=Path(directory) / 'queue', telegram_enabled=flag)
    def test_keyword_feed_defers_missing_image_analysis_without_dropping_payload(self):
        from pipeline.base import RawDoc
        from pipeline.feed_backlog import FeedBacklog
        from pipeline import enrich, image_reading, normalize
        from pipeline.telegram_deferred import NeedsAnalysis
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'queue.sqlite'
            queue = FeedBacklog(path)
            queue.enqueue('blog', 'feed', RawDoc('blog', 'image', kind='html'))
            queue.close()
            with patch.dict(os.environ, {'COLLECT_FEED_KEYWORD_ONLY': '1'}), \
                 patch.object(job, 'MAX_MODEL_CALLS', 0), patch.object(job, '_feed_document_known', return_value=False), \
                 patch.object(enrich, 'llm_available'), patch.object(image_reading, 'read_images'), \
                 patch.object(normalize, 'to_markdown', side_effect=NeedsAnalysis('missing cache')):
                result = job.run_minimal_blog(None, object(), queue_path=path)
            self.assertEqual(result['deferred_analysis'], 1)
            queue = FeedBacklog(path)
            self.assertEqual(queue.conn.execute("SELECT count(*) FROM pending WHERE defer_reason='analysis'").fetchone()[0], 1)
            self.assertIsNone(queue.next())
            queue.close()
    def test_blog_text_publication_keeps_unresolved_image_original_for_later(self):
        from pipeline.base import RawDoc
        from pipeline.feed_backlog import FeedBacklog
        from pipeline import image_reading, normalize, telegram_deferred
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'queue.sqlite'
            queue = FeedBacklog(path)
            queue.enqueue('blog', 'feed', RawDoc('blog', 'new', raw_content='<p>text</p><img src="https://example.com/a.png">', kind='html'))
            seq = queue.next()[0]
            queue.defer_revision(seq, reason='analysis')
            queue.close()
            def cached(items, *, missing, **kwargs):
                missing.append('synthetic-image')
                return {'synthetic-image': None}
            def normalize_text(doc):
                image_reading.read_images([{'key': 'synthetic-image'}])
                return 'text'
            with patch.dict(os.environ, {'COLLECT_FEED_STRICT_IMAGES': '1', 'COLLECT_FEED_KEYWORD_ONLY': '0'}), \
                 patch.object(job, 'MAX_MODEL_CALLS', 2), patch.object(job, '_feed_document_known', return_value=False), \
                 patch.object(telegram_deferred, 'cached_images', side_effect=cached), \
                 patch.object(image_reading, 'read_images'), patch.object(normalize, 'to_markdown', side_effect=normalize_text), \
                 patch.object(trial, 'run_documents', return_value={'counts': {}, 'stats': {}, 'published': 1}) as publish:
                result = job.run_minimal_blog(None, object(), queue_path=path)
            self.assertEqual(result['published'], 1)
            self.assertEqual(result['deferred_analysis'], 1)
            publish.assert_called_once()
            queue = FeedBacklog(path)
            retained = list(queue.analysis_pending())
            self.assertEqual(len(retained), 1)
            self.assertIn('<img', retained[0][2].raw_content)
            queue.close()
            class EmptyBlog:
                def discover(self): return []
            with patch.dict(os.environ, {'COLLECT_FEED_STRICT_IMAGES': '1', 'COLLECT_FEED_KEYWORD_ONLY': '0'}), \
                 patch.object(job, 'MAX_MODEL_CALLS', 2), patch.object(job, '_feed_document_known', return_value=True), \
                 patch.object(image_reading, 'read_images'), patch.object(trial, 'run_documents') as publish:
                again = job.run_minimal_blog(None, EmptyBlog(), queue_path=path)
            self.assertEqual(again['published'], 0)
            publish.assert_not_called()
            queue = FeedBacklog(path)
            self.assertEqual(len(list(queue.analysis_pending())), 1)
            queue.close()
    def test_telegram_page_is_preserved_when_grouping_marks_conflict(self):
        from pipeline.base import SourceRef
        from pipeline.feed_backlog import FeedBacklog
        from pipeline.telegram_marks_sync import GroupMarks, GroupMarkConflict

        class Blog:
            def discover(self): return [SourceRef('feed')]
            def discover_posts(self, ref): return []

        class Telegram:
            def discover(self): return [SourceRef('channel')]

        messages = [{'message_id': str(n), 'content': 'text', 'date': f'2026-01-01T00:0{n}:00Z',
                     'link': 'https://example.test', 'images': []} for n in (1, 2)]
        with TemporaryDirectory() as directory, \
             patch('services.telegram_service.scrape_channel', return_value=messages), \
             patch.object(GroupMarks, 'get', side_effect=GroupMarkConflict('synthetic conflict')):
            path = Path(directory) / 'queue.sqlite'
            flag = Path(directory) / 'telegram-trial'
            flag.write_text('feed-telegram-fallback-trial-v1\n'); flag.chmod(0o600)
            conflict = False
            for _ in range(2):
                try:
                    job.run_minimal_blog(None, Blog(), queue_path=path, telegram=Telegram(), telegram_trial=flag)
                except GroupMarkConflict:
                    conflict = True
                    break
            self.assertTrue(conflict)
            queue = FeedBacklog(path)
            self.assertEqual(queue.next_pending_ref(allowed={'telegram'})[2].meta['messages'], messages)
            self.assertIsNone(queue.next())
            queue.close()

    def test_telegram_gap_fallback_publishes_text_and_retains_source_page(self):
        from pipeline.base import SourceRef
        from pipeline.feed_backlog import FeedBacklog
        from pipeline import image_reading, telegram_deferred, telegram_marks_sync
        from tests.test_telegram_marks_sync import FakePG
        class Blog:
            def discover(self): return [SourceRef('feed')]
            def discover_posts(self, ref): return []
        class Telegram:
            def discover(self): return [SourceRef('channel')]
        messages = [{'message_id': str(n), 'content': 'synthetic', 'date': f'2026-01-01T00:0{n}:00Z',
                     'link': 'https://example.test', 'images': ['https://example.test/image']} for n in (1, 2)]
        with TemporaryDirectory() as directory:
            root = Path(directory); path = root / 'queue.sqlite'; work = root / 'work.sqlite'
            flag = root / 'telegram-trial'
            flag.write_text('feed-telegram-fallback-trial-v1\n'); flag.chmod(0o600)
            with sqlite3.connect(work) as db:
                db.execute("CREATE TABLE telegram_group_marks(channel TEXT,msg_id INTEGER,joins_prev INTEGER,model TEXT,judged_at TEXT DEFAULT (datetime('now')),PRIMARY KEY(channel,msg_id))")
                db.execute('CREATE TABLE image_readings(image_key TEXT,status TEXT,attempts INTEGER)')
            pg = FakePG(); marks = telegram_marks_sync.GroupMarks(lambda: pg, lambda: sqlite3.connect(work))
            def publish(_pg, connectors, cap, before_publish):
                docs = connectors[0].fetch(None)
                self.assertEqual(len(docs), 1)
                self.assertTrue(docs[0].raw_content)
                before_publish()
                return {'counts': {'new': 1}, 'stats': {}, 'published': 1}
            with patch.dict(os.environ, {'COLLECT_FEED_STRICT_IMAGES': '1', 'COLLECT_FEED_KEYWORD_ONLY': '0'}), \
                 patch.object(job, 'MAX_MODEL_CALLS', 2), patch.object(job, 'MAX_NEW_DOCS', 1), \
                 patch.object(job, '_feed_document_known', return_value=False), \
                 patch('services.telegram_service.scrape_channel', return_value=messages), \
                 patch.object(telegram_marks_sync, '_guard'), patch.object(telegram_marks_sync, 'GroupMarks', return_value=marks), \
                 patch.object(telegram_deferred, 'get_connection', side_effect=lambda: sqlite3.connect(work)), \
                 patch.object(image_reading, 'read_images'), patch.object(trial, 'run_documents', side_effect=publish) as run:
                for _ in range(2):
                    job.run_minimal_blog(None, Blog(), queue_path=path, telegram=Telegram(), telegram_trial=flag)
                    if run.called: break
            run.assert_called_once()
            self.assertFalse(flag.exists())
            self.assertEqual(len(pg.rows), 1)
            queue = FeedBacklog(path)
            self.assertIsNone(queue.next_pending_ref())
            self.assertEqual(queue.conn.execute("SELECT count(*) FROM pending_refs WHERE connector='telegram' AND revision_pending=1").fetchone()[0], 1)
            queue.close()

    def test_persistent_telegram_fallback_preserves_flag_and_conflicting_page(self):
        from pipeline.base import SourceRef
        from pipeline.feed_backlog import FeedBacklog
        from pipeline.telegram_marks_sync import GroupMarks, GroupMarkConflict
        class Blog:
            def discover(self): return [SourceRef('feed')]
            def discover_posts(self, ref): return []
        class Telegram:
            def discover(self): return [SourceRef('channel')]
        messages = [{'message_id': str(n), 'content': 'synthetic', 'date': f'2026-01-01T00:0{n}:00Z',
                     'link': 'https://example.test', 'images': []} for n in (1, 2)]
        with TemporaryDirectory() as directory, \
             patch('services.telegram_service.scrape_channel', return_value=messages), \
             patch.object(GroupMarks, 'get', side_effect=GroupMarkConflict('synthetic conflict')):
            root = Path(directory); path = root / 'queue'; flag = root / 'enabled'
            flag.write_text('feed-telegram-fallback-enabled-v1\n'); flag.chmod(0o600)
            conflict = False
            for _ in range(2):
                try:
                    job.run_minimal_blog(None, Blog(), queue_path=path, telegram=Telegram(), telegram_enabled=flag)
                except GroupMarkConflict:
                    conflict = True
                    break
            self.assertTrue(conflict)
            self.assertTrue(flag.exists())
            queue = FeedBacklog(path)
            self.assertEqual(queue.next_pending_ref(allowed={'telegram'})[2].meta['messages'], messages)
            queue.close()

    def test_optional_youtube_stages_discovered_refs_and_retries_missing_transcripts(self):
        from pipeline.base import SourceRef
        from pipeline.feed_backlog import FeedBacklog
        seen = []

        class Blog:
            def discover(self):
                return [SourceRef('blog-feed')]
            def discover_posts(self, ref):
                seen.append('blog')
                return []

        class YouTube:
            def discover_channels(self):
                return [SourceRef('channel')]
            def discover_channel(self, ref):
                seen.append('youtube')
                return [SourceRef('video', {'channel_id': 'channel'})]
            def fetch(self, ref):
                return []

        with TemporaryDirectory() as directory:
            path = Path(directory) / 'queue.sqlite'
            for _ in range(2):
                job.run_minimal_blog(None, Blog(), queue_path=path, youtube=YouTube())
            self.assertEqual(set(seen), {'blog', 'youtube'})
            queue = FeedBacklog(path)
            self.assertEqual(queue.next_pending_ref()[2].key, 'video')
            self.assertIsNone(queue.next())
            queue.close()
    def test_feed_refresh_preserves_queue_and_refuses_unpublished_work(self):
        from pipeline.base import RawDoc
        from pipeline.feed_backlog import FeedBacklog
        with TemporaryDirectory() as directory:
            source, target, path = [Path(directory) / name for name in ('source', 'target', 'queue')]
            for file, value in ((source, 'newer'), (target, 'older')):
                db = sqlite3.connect(file)
                db.executescript('''
                    CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, body TEXT);
                    CREATE TABLE entities(id INTEGER PRIMARY KEY); CREATE TABLE entity_keywords(id INTEGER PRIMARY KEY);
                    CREATE TABLE entity_relations(id INTEGER PRIMARY KEY);
                    CREATE TABLE candidate_publish_floor(name TEXT PRIMARY KEY,value INTEGER);
                    INSERT INTO candidate_publish_floor VALUES ('document_floor',1),('entity_floor',0),('keyword_floor',0),('relation_floor',0);
                ''')
                db.execute('INSERT INTO raw_documents VALUES(1,?)', (value,))
                db.commit(); db.close()
            q = FeedBacklog(path)
            q.enqueue('blog', 'ref', RawDoc('blog', 'id'))
            q.close()
            feed_refresh.refresh(source, target, path)
            db = sqlite3.connect(target)
            self.assertEqual(db.execute('SELECT body FROM raw_documents').fetchone()[0], 'newer')
            db.execute('INSERT INTO raw_documents VALUES(2,?)', ('unpublished',))
            db.commit(); db.close()
            with self.assertRaises(ValueError):
                feed_refresh.refresh(source, target, path)
            db = sqlite3.connect(target)
            self.assertEqual(db.execute('SELECT count(*) FROM raw_documents').fetchone()[0], 2)
            db.close()
            q = FeedBacklog(path)
            self.assertIsNotNone(q.next())
            q.close()
    def test_feed_sync_appends_only_validated_document_and_preserves_existing_rows(self):
        with TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ('source', 'target')]
            for path in paths:
                db = sqlite3.connect(path)
                db.executescript('''
                    CREATE TABLE raw_documents(id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT);
                    CREATE TABLE enrichments(id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER, summary TEXT);
                    CREATE TABLE entity_links(id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER, entity_id INTEGER);
                    CREATE TABLE entities(id INTEGER PRIMARY KEY); CREATE TABLE entity_keywords(id INTEGER PRIMARY KEY);
                    CREATE TABLE entity_relations(id INTEGER PRIMARY KEY);
                    CREATE TABLE candidate_publish_floor(name TEXT PRIMARY KEY,value INTEGER);
                    INSERT INTO candidate_publish_floor VALUES ('document_floor',1),('entity_floor',0),('keyword_floor',0),('relation_floor',0);
                    INSERT INTO raw_documents VALUES(1,'old');
                ''')
                db.commit()
                db.close()
            db = sqlite3.connect(paths[0])
            db.executescript("INSERT INTO raw_documents VALUES(2,'new'); INSERT INTO enrichments VALUES(1,2,'summary');"
                             "INSERT INTO entities VALUES(1); INSERT INTO entity_links VALUES(1,2,1);"
                             "UPDATE candidate_publish_floor SET value=2 WHERE name='document_floor';"
                             "UPDATE candidate_publish_floor SET value=1 WHERE name='entity_floor';")
            db.commit()
            db.close()
            self.assertEqual(feed_sync.sync(*paths), {'raw_documents': 1, 'enrichments': 1, 'entity_links': 1})
            db = sqlite3.connect(paths[1])
            self.assertEqual(db.execute('SELECT count(*) FROM raw_documents').fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT value FROM candidate_publish_floor WHERE name='document_floor'").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT seq FROM sqlite_sequence WHERE name='raw_documents'").fetchone()[0], 2)
            db.close()
            with self.assertRaises(ValueError):
                feed_sync.sync(*paths)

    def test_feed_batch_defers_existing_before_publishing_new(self):
        from pipeline.base import RawDoc
        from pipeline.feed_backlog import FeedBacklog
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'queue.sqlite'
            queue = FeedBacklog(path)
            queue.enqueue('blog', 'feed', RawDoc('blog', 'existing'))
            queue.enqueue('blog', 'feed', RawDoc('blog', 'fresh'))
            queue.close()
            result = {'counts': {'new': 1}, 'stats': {}, 'published': [1]}
            with patch.object(job, '_feed_document_known', side_effect=lambda _source, key: key == 'existing'), \
                 patch.object(trial, 'run_documents', return_value=result):
                job.run_minimal_blog(None, object(), queue_path=path)
            queue = FeedBacklog(path)
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending WHERE revision_pending=1').fetchone()[0], 1)
            self.assertIsNone(queue.next())
            queue.close()

    def test_feed_sync_requires_new_graph_relations_to_belong_to_published_batch(self):
        with TemporaryDirectory() as directory:
            source, target = [Path(directory) / name for name in ('source', 'target')]
            for path in (source, target):
                db = sqlite3.connect(path)
                db.executescript('''
                    CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, body TEXT);
                    CREATE TABLE enrichments(id INTEGER PRIMARY KEY, doc_id INTEGER);
                    CREATE TABLE entity_links(id INTEGER PRIMARY KEY, doc_id INTEGER, entity_id INTEGER);
                    CREATE TABLE entities(id INTEGER PRIMARY KEY);
                    CREATE TABLE entity_keywords(id INTEGER PRIMARY KEY, entity_id INTEGER);
                    CREATE TABLE entity_relations(id INTEGER PRIMARY KEY, src_id INTEGER, dst_id INTEGER, source_doc_id INTEGER);
                    CREATE TABLE candidate_publish_floor(name TEXT PRIMARY KEY,value INTEGER);
                    INSERT INTO candidate_publish_floor VALUES ('document_floor',0),('entity_floor',0),('keyword_floor',0),('relation_floor',0);
                ''')
                db.commit(); db.close()
            db = sqlite3.connect(source)
            db.executescript('''
                INSERT INTO raw_documents VALUES(1,'new'); INSERT INTO enrichments VALUES(1,1);
                INSERT INTO entities VALUES(1),(2); INSERT INTO entity_links VALUES(1,1,1);
                INSERT INTO entity_keywords VALUES(1,1); INSERT INTO entity_relations VALUES(1,1,2,99);
                UPDATE candidate_publish_floor SET value=1 WHERE name IN ('document_floor','keyword_floor','relation_floor');
                UPDATE candidate_publish_floor SET value=2 WHERE name='entity_floor';
            ''')
            db.commit(); db.close()
            with self.assertRaises(ValueError):
                feed_sync.sync(source, target)
            db = sqlite3.connect(target)
            self.assertEqual(db.execute('SELECT count(*) FROM raw_documents').fetchone()[0], 0)
            db.close()
            db = sqlite3.connect(source)
            db.execute('UPDATE entity_relations SET source_doc_id=1'); db.commit(); db.close()
            result = feed_sync.sync(source, target)
            self.assertEqual(result['raw_documents'], 1)
            db = sqlite3.connect(target)
            self.assertEqual(db.execute('SELECT count(*) FROM entity_relations').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM entity_keywords').fetchone()[0], 1)
            db.close()

    def test_recovery_requires_one_matching_complete_queued_document(self):
        from pipeline.base import RawDoc
        from pipeline.feed_backlog import FeedBacklog
        with TemporaryDirectory() as directory:
            queue = FeedBacklog(Path(directory) / 'queue.sqlite')
            queue.enqueue('blog', 'source', RawDoc('blog', 'id', raw_content='body'))
            work = sqlite3.connect(':memory:')
            work.executescript('''
                CREATE TABLE raw_documents(id INTEGER,source_type TEXT,source_id TEXT,raw_content TEXT,markdown TEXT,content_hash TEXT);
                CREATE TABLE enrichments(id INTEGER,doc_id INTEGER,content_hash TEXT,summary TEXT);
                CREATE TABLE entities(id INTEGER); CREATE TABLE entity_keywords(id INTEGER); CREATE TABLE entity_relations(id INTEGER);
                CREATE TABLE candidate_publish_floor(name TEXT PRIMARY KEY,value INTEGER);
                INSERT INTO candidate_publish_floor VALUES ('document_floor',0),('entity_floor',0),('keyword_floor',0),('relation_floor',0);
                INSERT INTO raw_documents VALUES (1,'blog','id','body','body','hash');
                INSERT INTO enrichments VALUES (1,1,'hash','summary');
            ''')
            seq, _, _ = recover.validate(work, queue)
            self.assertEqual(seq, queue.next()[0])
            work.execute("UPDATE enrichments SET content_hash='wrong'")
            with self.assertRaises(ValueError):
                recover.validate(work, queue)
            work.execute("UPDATE enrichments SET content_hash='hash'")
            work.execute("UPDATE candidate_publish_floor SET value=1 WHERE name='document_floor'")
            with self.assertRaises(ValueError):
                recover.validate(work, queue)
            recover.validate(work, queue, receipt_exists=True)
            queue.close()
            work.close()
    def test_model_budget_counts_primary_and_fallback_engine_attempts(self):
        from pipeline import llm
        from pipeline.llm_policies import resolve
        attempts = []

        def primary(*args, **kwargs):
            attempts.append('primary')
            raise RuntimeError('simulated primary failure')

        def fallback(*args, **kwargs):
            attempts.append('fallback')
            return llm.LLMResult(text='ok', model='test', engine='codex-exec')

        with patch.object(llm, '_run_claude_code', primary), patch.object(llm, '_run_codex', fallback), \
             patch.object(llm, '_run_api'), patch.object(llm, 'call_observer', None):
            refused = job._cap_table_model_calls(3)
            policy = resolve('document.tag', engine='claude-code', environ={})
            llm._execute('sample', policy=policy, record_call=lambda *_: None)
            with self.assertRaises(trial.Aborted):
                llm._execute('sample', policy=policy, record_call=lambda *_: None)
            self.assertEqual(attempts, ['primary', 'fallback', 'primary'])
            self.assertTrue(refused)

    def test_scheduled_compute_budget_counts_fallback_attempt(self):
        from pipeline import llm, postgres_scheduled_compute as compute
        from pipeline.llm_policies import resolve
        attempts = []

        def primary(*args, **kwargs):
            attempts.append('primary')
            raise RuntimeError('simulated primary failure')

        def fallback(*args, **kwargs):
            attempts.append('fallback')
            return llm.LLMResult(text='ok', model='test', engine='codex-exec')

        with patch.object(llm, '_run_claude_code', primary), patch.object(llm, '_run_codex', fallback), \
             patch.object(llm, '_run_api'), patch.object(llm, 'call_observer', None):
            compute._cap_model_calls(1)
            policy = resolve('document.tag', engine='claude-code', environ={})
            with self.assertRaises(compute.ModelBudgetExceeded):
                llm._execute('sample', policy=policy, record_call=lambda *_: None)
            self.assertEqual(attempts, ['primary'])
    def test_minimal_feed_keeps_unpublished_documents_after_failure(self):
        from pipeline.base import RawDoc, SourceRef
        from pipeline.feed_backlog import FeedBacklog

        class Connector:
            def discover(self):
                return [SourceRef('feed')]

            def discover_posts(self, _ref):
                return [SourceRef('first', {'post': {'url': 'first'}}), SourceRef('second', {'post': {'url': 'second'}})]

            def fetch_post(self, ref):
                return RawDoc('blog', ref.key)

        with TemporaryDirectory() as directory, patch.object(job, '_blog_document_known', return_value=False), \
             patch.object(job, '_feed_document_known', return_value=False):
            path = Path(directory) / 'backlog.sqlite'
            with patch.object(trial, 'run_documents', side_effect=RuntimeError('simulated publication failure')):
                with self.assertRaises(RuntimeError):
                    job.run_minimal_blog(None, Connector(), queue_path=path)
            queue = FeedBacklog(path)
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending').fetchone()[0], 1)
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending_refs').fetchone()[0], 1)
            queue.close()
            result = {'counts': {'new': 1}, 'stats': {}, 'published': 1}
            with patch.object(trial, 'run_documents', return_value=result):
                job.run_minimal_blog(None, Connector(), queue_path=path)
            queue = FeedBacklog(path)
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending').fetchone()[0], 0)
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending_refs').fetchone()[0], 1)
            queue.close()
    def test_media_is_readonly_and_feed_only(self):
        def spec(label, mount):
            return {'Image': engine.IMAGE, 'Labels': {engine.LABEL: '1', engine.LABEL + '.job': label},
                    'HostConfig': {'Binds': [mount], 'CapDrop': ['ALL'], 'NetworkMode': engine.NETWORK}}
        engine.check(spec('chain', 'explorer-refactor-media:/app/media:ro'))
        with self.assertRaises(ValueError):
            engine.check(spec('chain', 'explorer-refactor-media:/app/media'))
        with self.assertRaises(ValueError):
            engine.check(spec('prices', 'explorer-refactor-media:/app/media:ro'))

    def test_all_catchup_waits_until_priority_slot(self):
        with patch.dict(os.environ, {'COLLECT_CATCHUP_AFTER': '2026-11-17T22:10:00+00:00'}):
            self.assertEqual(scheduler.catchup_enabled({'history'}, datetime(2026, 11, 17, 22, 9, tzinfo=timezone.utc)), set())
            self.assertEqual(scheduler.catchup_enabled({'history'}, datetime(2026, 11, 17, 22, 10, tzinfo=timezone.utc)), {'history'})

    def test_work_volume_must_be_the_collection_volume(self):
        with patch.dict(os.environ, {'COLLECT_WORK_VOLUME': 'explorer-refactor-collect-recovery-20261118a'}):
            self.assertEqual(engine.work_volume(), 'explorer-refactor-collect-recovery-20261118a')
        with patch.dict(os.environ, {'COLLECT_WORK_VOLUME': 'explorer-refactor-media'}):
            with self.assertRaises(ValueError):
                engine.work_volume()

    def test_feed_work_volume_is_explicit_and_restricted(self):
        with patch.dict(os.environ, {'COLLECT_FEED_WORK_VOLUME': 'explorer-refactor-collect-feed-test'}):
            self.assertEqual(engine.feed_work_volume(), 'explorer-refactor-collect-feed-test')
        with patch.dict(os.environ, {'COLLECT_FEED_WORK_VOLUME': 'explorer-refactor-media'}):
            with self.assertRaises(ValueError):
                engine.feed_work_volume()

    def test_feed_failure_does_not_hold_other_jobs(self):
        with TemporaryDirectory() as directory, \
             patch.object(scheduler, 'HOLD', Path(directory) / 'global'), \
             patch.object(scheduler, 'FEED_HOLD', Path(directory) / 'feed'), \
             patch.dict(os.environ, {'COLLECT_CHAIN_INTAKE_ONLY': '1', 'COLLECT_FEED_WORK_VOLUME': 'explorer-refactor-collect-feed-test'}), \
             patch.object(scheduler, '_run_one', return_value=False):
            self.assertFalse(scheduler.run_job('chain', lambda *_: None))
            self.assertTrue(scheduler.FEED_HOLD.exists())
            self.assertFalse(scheduler.HOLD.exists())

    def test_feed_refresh_and_sync_failures_use_separate_holds(self):
        with TemporaryDirectory() as directory, \
             patch.object(scheduler, 'HOLD', Path(directory) / 'global'), \
             patch.object(scheduler, 'FEED_HOLD', Path(directory) / 'feed'), \
             patch.dict(os.environ, {'COLLECT_CHAIN_INTAKE_ONLY': '1', 'COLLECT_FEED_WORK_VOLUME': 'explorer-refactor-collect-feed-test',
                                     'COLLECT_FEED_AUTO_SYNC': '1'}), \
             patch.object(scheduler, '_run_one', return_value=True), \
             patch.object(engine, 'feed_maintenance', side_effect=[False, True, False]):
            self.assertFalse(scheduler.run_job('chain', lambda *_: None))
            self.assertTrue(scheduler.FEED_HOLD.exists())
            self.assertFalse(scheduler.HOLD.exists())
            scheduler.FEED_HOLD.unlink()
            self.assertFalse(scheduler.run_job('chain', lambda *_: None))
            self.assertTrue(scheduler.FEED_HOLD.exists())
            self.assertTrue(scheduler.HOLD.exists())

    def test_zero_model_cap_is_scoped_to_keyword_feed(self):
        with patch.dict(os.environ, {'COLLECT_FEED_KEYWORD_ONLY': '1', 'COLLECT_MAX_MODEL_CALLS': '5'}), \
             patch.object(engine, 'run', return_value=(0, '{"outcome":"applied: ok"}')) as run:
            self.assertTrue(scheduler._run_one('chain', lambda *_: None))
            self.assertEqual(run.call_args.kwargs['extra_env']['COLLECT_MAX_MODEL_CALLS'], '0')
            self.assertEqual(os.environ['COLLECT_MAX_MODEL_CALLS'], '5')

    def test_model_feed_is_limited_to_one_document_and_two_attempts(self):
        with patch.dict(os.environ, {'COLLECT_FEED_KEYWORD_ONLY': '0', 'COLLECT_FEED_STRICT_IMAGES': '1',
                                     'COLLECT_FEED_MODEL_ATTEMPTS': '2'}), \
             patch.object(engine, 'run', return_value=(0, '{"outcome":"applied: ok"}')) as run:
            self.assertTrue(scheduler._run_one('chain', lambda *_: None))
            self.assertEqual(run.call_args.kwargs['extra_env']['COLLECT_MAX_MODEL_CALLS'], '2')
            self.assertEqual(run.call_args.kwargs['extra_env']['COLLECT_MAX_NEW_DOCS'], '1')
        with patch.dict(os.environ, {'COLLECT_FEED_KEYWORD_ONLY': '0', 'COLLECT_FEED_STRICT_IMAGES': '1',
                                     'COLLECT_FEED_MODEL_ATTEMPTS': '3'}):
            with self.assertRaises(ValueError):
                scheduler._run_one('chain', lambda *_: None)

    def test_us_briefing_requires_synthesis(self):
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE job_runs(id INTEGER, job TEXT, summary TEXT, ran_at TEXT)')
        conn.execute('INSERT INTO job_runs VALUES (1,?,?,?)', ('compute_briefing', 'status ok · synthesis False', '2026-11-18 00:00:00'))
        with self.assertRaises(trial.HeldBack):
            job.require_us_briefing_synthesis(conn, '2026-11-18 00:00:00')
        conn.execute('UPDATE job_runs SET summary=?', ('status ok · synthesis True',))
        job.require_us_briefing_synthesis(conn, '2026-11-18 00:00:00')
        conn.close()

    def test_partial_briefing_requires_legacy_headline_failure_and_movers(self):
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE job_runs(id INTEGER, job TEXT, status TEXT, summary TEXT, ran_at TEXT)')
        conn.execute('INSERT INTO job_runs VALUES (1,?,?,?,?)', ('compute_briefing', 'partial',
                     'status partial · movers 3 · synthesis False · headline_failed 1', '2026-11-18 00:00:00'))
        self.assertEqual(job.validate_partial_us_briefing(conn, '2026-11-18 00:00:00'),
                         {'movers': 3, 'synthesis': False, 'headline_failed': 1})
        for summary in ('status partial · movers 0 · synthesis True · headline_failed 1',
                        'status partial · movers 3 · synthesis True · headline_failed 0',
                        'status partial · movers 3 · synthesis True', 'status error'):
            conn.execute('UPDATE job_runs SET summary=?', (summary,))
            with self.assertRaises(trial.HeldBack):
                job.validate_partial_us_briefing(conn, '2026-11-18 00:00:00')
        conn.close()

    def test_partial_job_record_is_opt_in_and_errors_stay_held(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'work.db'
            conn = sqlite3.connect(path)
            conn.execute('CREATE TABLE job_runs(id INTEGER, job TEXT, status TEXT, ran_at TEXT)')
            conn.execute('INSERT INTO job_runs VALUES (1,?,?,?)', ('compute_briefing', 'partial', '2026-11-18 00:00:00'))
            conn.commit()
            with patch.object(trial, 'WORK', str(path)):
                with self.assertRaises(trial.HeldBack):
                    trial._job_record('compute_briefing', '2026-11-18 00:00:00')
                self.assertEqual(trial._job_record('compute_briefing', '2026-11-18 00:00:00', ('ok', 'partial')), 'partial')
                conn.execute("UPDATE job_runs SET status='error'")
                conn.commit()
                with self.assertRaises(trial.HeldBack):
                    trial._job_record('compute_briefing', '2026-11-18 00:00:00', ('ok', 'partial'))
            conn.close()

    def test_scheduler_accepts_only_verified_briefing_partial(self):
        with patch.object(engine, 'run', return_value=(0, '{"outcome":"partial: US briefing headline failures; job_runs 1"}')):
            self.assertTrue(scheduler._run_one('usbriefing', lambda *_: None))
            self.assertFalse(scheduler._run_one('prices', lambda *_: None))
        with patch.object(engine, 'run', return_value=(0, '{"outcome":"partial: unknown"}')):
            self.assertFalse(scheduler._run_one('usbriefing', lambda *_: None))

    def test_send_secrets_require_explicit_key_selection(self):
        with TemporaryDirectory() as directory:
            secret_file = Path(directory) / 'secrets'
            secret_file.write_text('DART_API_KEY=test\nTELEGRAM_BOT_TOKEN=test\nTELEGRAM_CHAT_ID=test\n')
            secret_file.chmod(0o600)
            with patch.object(engine, 'SECRETS_FILE', secret_file):
                self.assertEqual(set(engine.secrets()), {'DART_API_KEY'})
                self.assertEqual(set(engine.secrets(engine.SECRET_KEYS + engine.SEND_KEYS)),
                                 {'DART_API_KEY', *engine.SEND_KEYS})

    def test_only_connected_send_can_be_enabled(self):
        scheduler.check_enabled({'briefing', 'observeweekly', 'observealerts', 'pfintraday'})
        with self.assertRaises(SystemExit):
            scheduler.check_enabled({'pfclose'})

    def test_observation_alert_waits_for_configured_slot(self):
        with patch.dict(os.environ, {'COLLECT_OBSERVE_ALERTS_AFTER': '2026-11-18T01:00:00+09:00'}):
            jobs = [('observealerts', [], 3600)]
            before = datetime.fromisoformat('2026-11-18T00:59:00+09:00')
            after = datetime.fromisoformat('2026-11-18T01:00:00+09:00')
            intervals = {}
            self.assertEqual(scheduler.due_now(jobs, {'observealerts'}, before, before, intervals), [])
            self.assertEqual(scheduler.due_now(jobs, {'observealerts'}, before, after, intervals), ['observealerts'])

    def test_price_catchup_waits_for_the_next_slot(self):
        with patch.dict(os.environ, {'COLLECT_PRICES_CATCHUP_AFTER': '2026-11-18T07:35:00+00:00'}):
            self.assertEqual(scheduler.catchup_enabled({'prices', 'watch'}, datetime(2026, 11, 18, 7, 34, tzinfo=timezone.utc)), {'watch'})
            self.assertEqual(scheduler.catchup_enabled({'prices', 'watch'}, datetime(2026, 11, 18, 7, 35, tzinfo=timezone.utc)), {'prices', 'watch'})

    def test_us_briefing_catchup_waits_for_market_close_slot(self):
        with patch.dict(os.environ, {'COLLECT_USBRIEFING_CATCHUP_AFTER': '2026-11-17T21:30:00+00:00'}):
            self.assertEqual(scheduler.catchup_enabled({'usbriefing'}, datetime(2026, 11, 17, 21, 29, tzinfo=timezone.utc)), set())
            self.assertEqual(scheduler.catchup_enabled({'usbriefing'}, datetime(2026, 11, 17, 21, 30, tzinfo=timezone.utc)), {'usbriefing'})

    def test_source_stop_is_not_swallowed_by_library_retry(self):
        def retrying_client():
            try:
                raise trial.Aborted('request cap')
            except Exception:
                return 'retry'

        with self.assertRaises(trial.Aborted):
            retrying_client()

    def test_chain_intake_only_runs_one_step(self):
        with TemporaryDirectory() as directory, patch.object(scheduler, 'HOLD', Path(directory) / 'hold'), \
             patch.dict(os.environ, {'COLLECT_CHAIN_INTAKE_ONLY': '1'}), \
             patch.object(scheduler, '_run_one', return_value=True) as run:
            self.assertTrue(scheduler.run_job('chain', lambda *_: None))
            self.assertEqual([args[0][0] for args in run.call_args_list], ['chain'])

    def test_target_guard(self):
        live = 'refactor_fixture_' + 'a' * 32
        clone = 'refactor_fixture_' + 'b' * 32
        driver = types.SimpleNamespace(connect=lambda *args, **kwargs: 'connected')
        for mode, schema, allowed in [('', live, False), ('', clone, True),
                                      ('live', live, True), ('live', clone, False),
                                      ('live', 'invalid', False)]:
            with self.subTest(mode=mode, allowed=allowed), patch.dict(os.environ, {
                'REFACTOR_POSTGRES_DSN': 'test', 'TRIAL_LIVE_SCHEMA': live,
                'REFACTOR_FIXTURE_SCHEMA': schema, 'COLLECT_TARGET': mode,
            }), patch.dict(sys.modules, {'psycopg': driver}):
                if allowed:
                    self.assertEqual(trial._pg(), 'connected')
                else:
                    with self.assertRaises(ValueError):
                        trial._pg()

    def test_scheduler_holds_on_failure_and_after_interruption(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / 'hold'
            with patch.object(scheduler, 'HOLD', marker):
                with patch.object(scheduler, '_run_one', return_value=True):
                    self.assertTrue(scheduler.run_job('prices', lambda *_: None))
                    self.assertFalse(marker.exists())
                with patch.object(scheduler, '_run_one', return_value=False):
                    self.assertFalse(scheduler.run_job('prices', lambda *_: None))
                    self.assertTrue(marker.exists())
                with patch.object(scheduler, '_run_one') as run:
                    self.assertFalse(scheduler.run_job('watch', lambda *_: None))
                    run.assert_not_called()
                marker.unlink()
                with patch.object(scheduler, '_run_one', side_effect=RuntimeError('interrupted')):
                    with self.assertRaises(RuntimeError):
                        scheduler.run_job('prices', lambda *_: None)
                    self.assertTrue(marker.exists())

    def test_recorded_backup_space_refusal_does_not_block_collection(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / 'hold'
            with patch.object(scheduler, 'HOLD', marker), \
                 patch.object(scheduler, '_run_one', return_value=scheduler.SAFE_BACKUP_REFUSAL):
                self.assertFalse(scheduler.run_job('pgbackup', lambda *_: None))
                self.assertFalse(marker.exists())

    def test_only_recorded_preflight_backup_refusal_is_safe(self):
        from types import SimpleNamespace
        refused = SimpleNamespace(returncode=1, stdout='not enough VM space for a backup\n', stderr='')
        with patch('subprocess.run', return_value=refused), patch.object(engine, 'run', return_value=(0, '')):
            self.assertIs(scheduler._run_one('pgbackup', lambda *_: None), scheduler.SAFE_BACKUP_REFUSAL)
        with patch('subprocess.run', return_value=refused), patch.object(engine, 'run', return_value=(1, '')):
            self.assertFalse(scheduler._run_one('pgbackup', lambda *_: None))
        failed = SimpleNamespace(returncode=1, stdout='different failure\n', stderr='')
        with patch('subprocess.run', return_value=failed), patch.object(engine, 'run', return_value=(0, '')):
            self.assertFalse(scheduler._run_one('pgbackup', lambda *_: None))


if __name__ == '__main__':
    unittest.main()
