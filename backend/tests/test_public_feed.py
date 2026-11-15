"""Original source selection using only current reviewed snapshots."""
from datetime import datetime, timezone
import sqlite3
import unittest
import test_public_documents as fixtures
from security.public_feed import public_feed, feed_metadata
from security.public_documents import DocumentUnavailable

class PublicFeedTests(unittest.TestCase):
    setUp = fixtures.PublicDocumentTests.setUp
    mutate = fixtures.PublicDocumentTests.mutate
    def test_collection_reads_indexed_documents_and_stored_summaries_without_approvals(self):
        with sqlite3.connect(self.source) as conn:
            conn.executescript('''CREATE TABLE enrichments(id INTEGER PRIMARY KEY,doc_id INTEGER,summary TEXT,enriched_at TEXT);
                INSERT INTO enrichments VALUES(1,1,'Stored summary','2026-11-14');
                CREATE TABLE public_collection_index(doc_id INTEGER PRIMARY KEY,channel TEXT,name TEXT,
                    platform TEXT,title TEXT,published_at TEXT,sort_at TEXT);
                INSERT INTO public_collection_index VALUES(1,'web:example.test','example.test','web',
                    'Reviewed title','2026-11-14','2026-11-14T00:00:00+00:00');''')
        document = self.client.get('/api/public/documents/1')
        self.assertEqual(document.status_code, 200)
        self.assertEqual(document.json()['summary'], 'Stored summary')
        self.assertEqual(self.client.get('/api/public/documents/1/attachments/0').content, fixtures.PNG)
        self.assertEqual(self.client.get('/api/public/documents/2').status_code, 404)
        self.assertEqual([item['id'] for item in self.client.get('/api/public/feed').json()['items']], [1])
        self.assertEqual([item['id'] for item in self.client.get('/api/public/documents?q=BODY').json()['items']], [1])
        self.assertEqual(self.client.get('/api/public/documents?q=private-canary').json()['items'], [])
    def test_channel_navigation_and_changed_source_requires_review(self):
        with sqlite3.connect(self.source) as conn:
            conn.executescript("""ALTER TABLE raw_documents ADD COLUMN source_id TEXT;
                CREATE TABLE telegram_channels(channel_name TEXT, display_name TEXT);
                INSERT INTO telegram_channels VALUES('one','첫 채널'),('two','둘째 채널');
                UPDATE raw_documents SET source_type='telegram',source_id='one/1' WHERE id=1;
                INSERT INTO raw_documents(id,title,source_type,source_id,url,published_at,markdown,media_json)
                VALUES(3,'Second','telegram','two/3','https://example.test/second','2026-11-13','second body','[]');""")
        for id in (1, 3):
            preview = self.service.preview(id)
            self.store.approve(id,preview['fingerprint'],0,self.actor,'Synthetic sources',feed_metadata=feed_metadata(preview['document']))
        self.assertEqual(self.client.get('/api/public/feed?channel=telegram:two').status_code,200)
        self.assertEqual(self.client.post('/api/public/feed').status_code,404)
        before = self.source.read_bytes()
        all_feed = public_feed(self.service, until=datetime(2026,11,15,tzinfo=timezone.utc))
        self.assertEqual([c['id'] for c in all_feed['channels']], ['telegram:one','telegram:two'])
        self.assertEqual([i['id'] for i in public_feed(self.service,channel='telegram:two')['items']], [3])
        self.assertEqual(public_feed(self.service,platform='blog')['items'], [])
        self.assertEqual(public_feed(self.service,topic='Second')['items'][0]['id'], 3)
        self.assertNotIn('canary', str(all_feed))
        self.assertNotIn('unread', str(all_feed))
        self.assertEqual(self.source.read_bytes(),before)
        self.mutate("UPDATE telegram_channels SET display_name='Changed private label' WHERE channel_name='one'")
        with self.assertRaises(DocumentUnavailable): self.service.published(1)
        self.assertNotIn('Changed private label',str(public_feed(self.service)))
        self.assertEqual([i['id'] for i in public_feed(self.service)['items']], [3])
        self.assertEqual(public_feed(self.service)['channels'][0]['name'], '첫 채널')
        self.store.revoke(3,1,self.actor)
        self.store.revoke(1,1,self.actor)
        self.assertEqual(public_feed(self.service)['channels'], [])

    def test_page_cutoff_and_search_only_within_reviewed_corpus(self):
        with sqlite3.connect(self.source) as conn:
            for id in range(3,25):
                conn.execute('INSERT INTO raw_documents(id,title,source_type,url,published_at,markdown,media_json) VALUES(?,?,?,?,?,?,?)',
                    (id,str(id),'web','https://example.test/post/'+str(id),'2026-11-14','public body','[]'))
        for id in range(3,25):
            preview = self.service.preview(id)
            self.store.approve(id,preview['fingerprint'],0,self.actor,'Synthetic',feed_metadata=feed_metadata(preview['document']))
        first = public_feed(self.service)
        second = public_feed(self.service,page=2)
        self.assertEqual(len(first['items']),20)
        self.assertEqual(len(second['items']),2)
        self.assertTrue(first['has_more']); self.assertFalse(second['has_more'])
        self.assertFalse({i['id'] for i in first['items']} & {i['id'] for i in second['items']})
        self.assertEqual(first['channels'][0]['count'],22)
        self.assertEqual(public_feed(self.service,until=datetime(2026,11,13,tzinfo=timezone.utc))['items'],[])
        self.assertEqual(public_feed(self.service,topic='private-canary')['items'],[])

    def test_directory_over_1000_documents_reads_only_selected_page_bodies(self):
        from unittest.mock import patch
        from models.public_documents import PublishedDocument
        doc = PublishedDocument(id=1,title='title',source_type='web',url='https://example.test',published_at='2026-11-14',content='body',content_kind='stored_text',attachments=[])
        metadata = feed_metadata(doc)
        with self.store.connection() as conn, conn:
            import json
            conn.executemany("INSERT INTO publications(doc_id,fingerprint,version,status,rights_basis,approved_by,approved_at,feed_metadata) VALUES(?,?,1,'approved','fixture',?,0,?)",
                [(id, 'a'*64,self.actor,json.dumps(metadata)) for id in range(3,1504)])
        with patch.object(self.service,'published',side_effect=DocumentUnavailable) as capture:
            result = public_feed(self.service,page=40)
        self.assertEqual(result['channels'][0]['count'],1501)
        self.assertEqual(capture.call_count,20)
        self.assertTrue(result['has_more'])

    def test_explicit_v2_upgrade_preserves_approval_without_inventing_channel_metadata(self):
        self.store.approve(1,'b'*64,0,self.actor,'Existing approval')
        with self.store.connection() as conn, conn:
            conn.execute('ALTER TABLE publications DROP COLUMN feed_metadata')
            conn.execute('UPDATE publication_metadata SET version=2')
        before = self.store.get(1)
        self.store.initialize()
        after = self.store.get(1)
        self.assertIsNone(after.pop('feed_metadata'))
        self.assertEqual(after,before)
        with self.store.connection(readonly=True) as conn:
            self.assertEqual(conn.execute('SELECT version FROM publication_metadata').fetchone()[0],3)
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertEqual(public_feed(self.service)['channels'],[])
