"""Isolated PG document/conversation persistence and ownership checks."""
import json
import os
from pathlib import Path
import sqlite3
import unittest
import uuid

import psycopg
from psycopg import sql

from pipeline.postgres_conversations import (ConversationImportConflict, ConversationNotFound,
                                             DocumentNotFound, PostgreSQLConversations,
                                             import_sqlite_conversations)


@unittest.skipUnless(os.getenv('REFACTOR_TEST_DISPOSABLE') == '1', 'disposable fixture required')
class PostgreSQLConversationTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ['REFACTOR_POSTGRES_DSN']
        parts = psycopg.conninfo.conninfo_to_dict(self.dsn)
        if (parts.get('host'), parts.get('dbname'), parts.get('user')) != ('pg', 'fixture', 'fixture'):
            raise RuntimeError('Refusing non-fixture PostgreSQL')
        self.schema = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(self.dsn) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        with self.connect() as conn:
            conn.execute('CREATE TABLE document_projection (id BIGINT PRIMARY KEY, detail_document JSONB NOT NULL)')
            conn.execute('INSERT INTO document_projection VALUES (%s,%s::jsonb)', (7, json.dumps({'id': 7, 'title': 'Fixture document', 'source_type': 'fixture'})))
            conn.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/conversation_store.sql').read_text())
        self.store = PostgreSQLConversations(self.connect)

    def connect(self):
        return psycopg.connect(self.dsn, options=f'-c search_path={self.schema}')

    def tearDown(self):
        with psycopg.connect(self.dsn) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def test_document_question_answer_and_fresh_connection(self):
        cid, mid = self.store.create_question('What does the document say?', document_id=7)
        self.store.append_assistant(cid, 'Fixture answer', model='fixture', citations=[{'doc_id': 7}])
        # A new store and connection simulate a service process restart.
        reopened = PostgreSQLConversations(self.connect)
        conversation, messages = reopened.detail(cid)
        self.assertEqual(json.loads(conversation['state_json'])['attached_doc_ids'], [7])
        self.assertEqual([m['role'] for m in messages], ['user', 'assistant'])
        self.assertEqual(json.loads(messages[0]['attachments_json'])[0]['ref'], '7')
        self.assertEqual(json.loads(messages[1]['citations_json'])[0]['doc_id'], 7)
        self.assertEqual(reopened.list()[0]['message_count'], 2)
        self.assertEqual(messages[0]['id'], mid)

    def test_missing_document_does_not_create_a_conversation(self):
        with self.assertRaises(DocumentNotFound):
            self.store.create_question('Missing?', document_id=999)
        self.assertEqual(self.store.list(), [])

    def test_private_telegram_thread_is_not_read_or_written_by_other_owner(self):
        with self.connect() as conn:
            cid = conn.execute("INSERT INTO conversations(channel,chat_id) VALUES ('telegram','owner-a') RETURNING id").fetchone()[0]
        self.assertEqual(self.store.list(owner_chat_id='owner-b'), [])
        with self.assertRaises(ConversationNotFound):
            self.store.detail(cid, owner_chat_id='owner-b')
        with self.assertRaises(ConversationNotFound):
            self.store.create_question('not mine', conversation_id=cid, owner_chat_id='owner-b')
        self.assertEqual(len(self.store.list(owner_chat_id='owner-a')), 1)

    def make_source(self, *, document_id=7, source_has_document=True):
        source = sqlite3.connect(':memory:')
        source.executescript('''
            CREATE TABLE conversations(id INTEGER PRIMARY KEY, title TEXT, anchor_entity_id INTEGER,
              channel TEXT, chat_id TEXT, summary TEXT, state_json TEXT, created_at TEXT, updated_at TEXT);
            CREATE TABLE chat_messages(id INTEGER PRIMARY KEY, conversation_id INTEGER, role TEXT,
              content TEXT, citations_json TEXT, gaps_json TEXT, model TEXT, route_json TEXT,
              attachments_json TEXT, created_at TEXT);
            CREATE TABLE chat_entity_links(message_id INTEGER, entity_id INTEGER, link_type TEXT);
            CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,source_type TEXT,url TEXT,title TEXT,published_at TEXT);
        ''')
        if source_has_document:
            source.execute('INSERT INTO raw_documents VALUES(?,?,?,?,?)', (document_id, 'fixture', None, 'Fixture document', None))
        source.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?,?,?,?)',
                       (12, 'fixture', None, 'web', None, None, json.dumps({'attached_doc_ids': [document_id]}), '2026-01-01', '2026-01-01'))
        source.execute('INSERT INTO chat_messages VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (23, 12, 'assistant', 'saved answer', json.dumps([{'doc_id': document_id}]), None, 'fixture', None, None, '2026-01-01'))
        return source

    def test_import_preserves_ids_references_and_rejects_second_import(self):
        source = self.make_source()
        with self.connect() as target:
            counts = import_sqlite_conversations(source, target)
        self.assertEqual(counts['conversations'], 1)
        self.assertEqual(counts['document_references'], 1)
        conversation, messages = self.store.detail(12)
        self.assertEqual(messages[0]['id'], 23)
        self.assertEqual(json.loads(messages[0]['citations_json'])[0]['doc_id'], 7)
        cid, _ = self.store.create_question('new question')
        self.assertGreater(cid, conversation['id'])
        with self.connect() as target, self.assertRaises(ConversationImportConflict):
            import_sqlite_conversations(source, target)
        source.close()

    def test_import_missing_document_leaves_target_empty(self):
        source = self.make_source(document_id=999)
        with self.connect() as target, self.assertRaises(ConversationImportConflict):
            import_sqlite_conversations(source, target)
        self.assertEqual(self.store.list(), [])
        source.close()

    def test_preexisting_missing_source_document_is_preserved_and_reported(self):
        source = self.make_source(document_id=999, source_has_document=False)
        with self.connect() as target:
            counts = import_sqlite_conversations(source, target)
        self.assertEqual(counts['documents_missing_in_source'], 1)
        with self.connect() as target:
            row = target.execute('SELECT document_id,reason FROM conversation_import_unresolved_docs').fetchone()
        self.assertEqual(row, (999, 'missing_in_source'))
        self.assertEqual(json.loads(self.store.detail(12)[1][0]['citations_json'])[0]['doc_id'], 999)
        source.close()

    def test_same_document_id_with_different_identity_is_rejected(self):
        source = self.make_source()
        source.execute('UPDATE raw_documents SET title=? WHERE id=7', ('different',))
        with self.connect() as target, self.assertRaises(ConversationImportConflict):
            import_sqlite_conversations(source, target)
        self.assertEqual(self.store.list(), [])
        source.close()

    def test_missing_source_document_stays_unresolved_even_if_pg_reuses_id(self):
        source = self.make_source(document_id=7, source_has_document=False)
        with self.connect() as target:
            counts = import_sqlite_conversations(source, target)
        self.assertEqual(counts['documents_missing_in_source'], 1)
        with self.connect() as target:
            self.assertEqual(target.execute('SELECT document_id FROM conversation_import_unresolved_docs').fetchone()[0], 7)
        source.close()
