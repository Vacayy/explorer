"""Isolated PG document/conversation persistence and ownership checks."""
import json
import os
from pathlib import Path
import unittest
import uuid

import psycopg
from psycopg import sql

from pipeline.postgres_conversations import ConversationNotFound, DocumentNotFound, PostgreSQLConversations


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
            conn.execute('INSERT INTO document_projection VALUES (%s,%s::jsonb)', (7, json.dumps({'id': 7, 'title': 'Fixture document'})))
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
