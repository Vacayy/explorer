"""Import conversation-search chunks into an isolated document generation."""
import os
from pathlib import Path
import sqlite3
import struct
import unittest

from pipeline.postgres_chat_chunks import ChatChunkImportConflict, PostgreSQLChunkSearch, import_chat_chunks
from pipeline.postgres_ingest_fixture import store_document
from pipeline.postgres_ingest_rebuild_fixture import rebuild
from pipeline.postgres_chunk_rag import PostgreSQLChunkRAG
import tests.test_postgres_ingest_fixture as fixtures


@unittest.skipUnless(os.getenv('REFACTOR_TEST_DISPOSABLE') == '1', 'disposable fixture required')
class PostgreSQLChatChunkTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.IngestFixtureTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        with self.fixture.pg() as conn:
            doc = store_document(conn, source_type='note', source_id='chunk-test', title='반도체',
                                 markdown='반도체 원문', raw_content='반도체 원문', published_at='2026-01-01')
            rebuild(conn)
            conn.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/chat_chunks.sql').read_text())
            raw = conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' AND row_data->>'id'=%s",
                               (str(doc['id']),)).fetchone()[0]
        self.doc_id = doc['id']
        self.source = sqlite3.connect(':memory:')
        self.addCleanup(self.source.close)
        self.source.executescript('''
          CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,source_type TEXT,url TEXT,title TEXT,published_at TEXT,content_hash TEXT);
          CREATE TABLE doc_chunks(id INTEGER PRIMARY KEY,doc_id INTEGER,idx INTEGER,text TEXT,prefix TEXT,content_hash TEXT);
          CREATE TABLE chunk_vec(rowid INTEGER PRIMARY KEY,embedding BLOB);
        ''')
        self.source.execute('INSERT INTO raw_documents VALUES(?,?,?,?,?,?)',
                            tuple(raw.get(k) for k in ('id', 'source_type', 'url', 'title', 'published_at', 'content_hash')))
        self.source.execute('INSERT INTO doc_chunks VALUES(?,?,?,?,?,?)', (31, self.doc_id, 0, '반도체 원문', '제목', raw.get('content_hash')))
        self.source.execute('INSERT INTO chunk_vec VALUES(?,?)', (31, struct.pack('<384f', *([0.1] * 384))))

    def test_import_preserves_chunks_vectors_and_rejects_reimport(self):
        with self.fixture.pg() as conn:
            result = import_chat_chunks(self.source, conn, document_ids=[self.doc_id])
        self.assertEqual(result, {'chunks': 1, 'documents': 1, 'stale_chunks': 0, 'complete': False})
        with self.fixture.pg() as conn:
            row = conn.execute('SELECT id,document_id,text,octet_length(embedding) FROM chat_chunk_projection').fetchone()
        self.assertEqual(row, (31, self.doc_id, '반도체 원문', 1536))
        with self.fixture.pg() as conn, self.assertRaises(ChatChunkImportConflict):
            import_chat_chunks(self.source, conn, document_ids=[self.doc_id])

    def test_changed_document_leaves_target_empty(self):
        self.source.execute('UPDATE raw_documents SET title=?', ('changed',))
        with self.fixture.pg() as conn, self.assertRaises(ChatChunkImportConflict):
            import_chat_chunks(self.source, conn, document_ids=[self.doc_id])
        with self.fixture.pg() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM chat_chunk_projection').fetchone()[0], 0)

    def test_bad_vector_leaves_target_empty(self):
        self.source.execute('UPDATE chunk_vec SET embedding=?', (b'bad',))
        with self.fixture.pg() as conn, self.assertRaises(ChatChunkImportConflict):
            import_chat_chunks(self.source, conn, document_ids=[self.doc_id])
        with self.fixture.pg() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM chat_chunk_projection').fetchone()[0], 0)

    def test_pg_chunks_reuse_original_hybrid_search_and_reject_generation_change(self):
        with self.fixture.pg() as conn:
            import_chat_chunks(self.source, conn, document_ids=[self.doc_id])

        class Model:
            def embed(self, queries):
                return [[0.1] * 384 for _ in queries]

        provider = lambda **kwargs: Model()
        with self.assertRaises(ChatChunkImportConflict):
            PostgreSQLChunkSearch(self.fixture.pg, provider)
        index = PostgreSQLChunkSearch(self.fixture.pg, provider, allow_partial=True)
        try:
            matches = index.search('반도체', k=5, pool=8)
            self.assertEqual(matches[0]['doc_id'], self.doc_id)
            self.assertEqual(matches[0]['text'], '반도체 원문')
            with self.fixture.pg() as conn:
                conn.execute("UPDATE snapshot_metadata SET generation_id='11111111-1111-1111-1111-111111111111'")
            with self.assertRaises(ChatChunkImportConflict):
                index.search('반도체', k=5, pool=8)
        finally:
            index.close()

    def test_postgres_rag_reads_document_and_applies_snapshot_entity_filter(self):
        with self.fixture.pg() as conn:
            generation = str(conn.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()[0])
            for table in ('telegram_channels', 'blog_sources', 'entity_links'):
                conn.execute("INSERT INTO legacy_snapshot_tables VALUES (%s,'[]'::jsonb,'fixture',0)", (table,))
            from psycopg.types.json import Jsonb
            conn.execute("INSERT INTO legacy_snapshot_rows VALUES ('entity_links',0,%s)",
                         (Jsonb({'doc_id': self.doc_id, 'entity_id': 5}),))

        class Chunks:
            connect = self.fixture.pg
        chunks = Chunks()
        chunks.generation = generation
        adapter = PostgreSQLChunkRAG(chunks, lambda *_: None)
        docs = adapter.fetch_docs([self.doc_id])
        self.assertEqual(docs[0]['id'], self.doc_id)
        self.assertEqual(adapter.apply_filters(docs, None, None, 5, None), docs)
        self.assertEqual(adapter.apply_filters(docs, None, None, 6, None), [])
        with self.fixture.pg() as conn:
            conn.execute("DELETE FROM legacy_snapshot_tables WHERE table_name='blog_sources'")
        with self.assertRaises(ChatChunkImportConflict):
            adapter.apply_filters(docs, None, None, None, None)

    def test_channel_scope_reuses_original_matcher_on_pg_metadata(self):
        from psycopg.types.json import Jsonb
        with self.fixture.pg() as conn:
            generation = str(conn.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()[0])
            for table in ('telegram_channels', 'blog_sources', 'youtube_channels', 'scrap_links'):
                conn.execute("INSERT INTO legacy_snapshot_tables VALUES (%s,'[]'::jsonb,'fixture',0)", (table,))
            conn.execute("INSERT INTO legacy_snapshot_rows VALUES ('telegram_channels',0,%s)",
                         (Jsonb({'channel_name': 'tech', 'display_name': '기술 소식'}),))
            conn.execute("INSERT INTO legacy_snapshot_rows VALUES ('raw_documents',99,%s)",
                         (Jsonb({'id': 99, 'source_type': 'telegram', 'source_id': 'tech/1',
                                 'url': '', 'published_at': '2026-01-01'}),))
        class Chunks:
            connect = self.fixture.pg
        chunks = Chunks()
        chunks.generation = generation
        adapter = PostgreSQLChunkRAG(chunks, lambda *_: None)
        ids, names, coverage = adapter.channel_scope('기술')
        self.assertEqual(ids, {99})
        self.assertEqual(names, ['기술 소식'])
        self.assertIn('1건', coverage)
        self.assertIsNone(adapter.channel_scope('없는 채널'))

    def test_entity_scope_resolves_name_alias_keyword_and_fuzzy_evidence(self):
        from psycopg.types.json import Jsonb
        with self.fixture.pg() as conn:
            generation = str(conn.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()[0])
            for table in ('entities', 'entity_keywords', 'entity_links'):
                conn.execute("INSERT INTO legacy_snapshot_tables VALUES (%s,'[]'::jsonb,'fixture',0)", (table,))
            conn.execute("INSERT INTO legacy_snapshot_rows VALUES ('entities',0,%s)",
                         (Jsonb({'id': 7, 'type': 'company', 'name': '테스트기업', 'aliases': 'ABC'}),))
            conn.execute("INSERT INTO legacy_snapshot_rows VALUES ('entity_keywords',0,%s)",
                         (Jsonb({'entity_id': 7, 'keyword': '테스트별칭', 'status': 'active'}),))
            for i in range(3):
                conn.execute("INSERT INTO legacy_snapshot_rows VALUES ('entity_links',%s,%s)",
                             (i, Jsonb({'doc_id': self.doc_id, 'entity_id': 7})))
        class Chunks:
            connect = self.fixture.pg
        chunks = Chunks()
        chunks.generation = generation
        adapter = PostgreSQLChunkRAG(chunks, lambda *_: None)
        for name in ('테스트기업', 'ABC', '테스트별칭'):
            entity_id, terms, assumptions = adapter.entity_scope(name)
            self.assertEqual(entity_id, 7)
            self.assertIn('테스트별칭', terms)
            self.assertEqual(assumptions, {})
        entity_id, _, assumptions = adapter.entity_scope('테스트반도체')
        self.assertEqual(entity_id, 7)
        self.assertEqual(assumptions['assumed'][0]['entity_id'], 7)

    def test_fixture_chat_api_persists_question_and_answer_in_pg(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from pipeline.postgres_conversations import PostgreSQLConversations
        from routers.postgres_chat_fixture import create_router
        with self.fixture.pg() as conn:
            conn.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/conversation_store.sql').read_text())
        store = PostgreSQLConversations(self.fixture.pg)
        app = FastAPI()
        app.include_router(create_router(store, Mock()))
        turn = SimpleNamespace(answer='시험 답변', citations=[], gaps=[], model='fixture',
                               route={'intent': 'research', 'entities': []}, calls=[], route_log=lambda: {})
        with TestClient(app) as client, patch('pipeline.chat.run_turn', return_value=turn):
            response = client.post('/api/spine/ask', json={'question': '시험 질문'})
            self.assertEqual(response.status_code, 200)
            cid = response.json()['conversation_id']
            detail = client.get(f'/api/spine/conversations/{cid}')
            self.assertEqual(detail.status_code, 200)
            self.assertEqual([m['content'] for m in detail.json()['messages']], ['시험 질문', '시험 답변'])
            self.assertEqual(client.post('/api/spine/ask', json={'question': '질문', 'document_ids': [1]}).status_code, 422)
