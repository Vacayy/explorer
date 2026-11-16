import os
import sqlite3
import unittest
import uuid

import psycopg
from psycopg import sql
from pipeline.postgres_chat_preview_fork import fork_chat_preview
from pipeline.postgres_ingest_rebuild_fixture import rebuild
import tests.test_postgres_ingest_fixture as fixtures


@unittest.skipUnless(os.getenv('REFACTOR_TEST_DISPOSABLE') == '1', 'disposable fixture required')
class ChatPreviewForkTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.IngestFixtureTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        with self.fixture.pg() as pg:
            rebuild(pg)
        self.schema = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(self.fixture.dsn) as pg:
            pg.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_target)
        self.source = sqlite3.connect(':memory:')
        self.addCleanup(self.source.close)
        self.source.executescript('''
          CREATE TABLE conversations(id INTEGER,title TEXT,anchor_entity_id INTEGER,channel TEXT,chat_id TEXT,summary TEXT,state_json TEXT,created_at TEXT,updated_at TEXT);
          CREATE TABLE chat_messages(id INTEGER,conversation_id INTEGER,role TEXT,content TEXT,citations_json TEXT,gaps_json TEXT,model TEXT,route_json TEXT,attachments_json TEXT,created_at TEXT);
          CREATE TABLE chat_entity_links(message_id INTEGER,entity_id INTEGER,link_type TEXT);
          INSERT INTO conversations VALUES(1,'시험',NULL,'web',NULL,NULL,'{}','2026-01-01','2026-01-01');
          INSERT INTO chat_messages VALUES(2,1,'user','질문',NULL,NULL,NULL,NULL,NULL,'2026-01-01');
        ''')
        self.source.execute('PRAGMA query_only=ON')
        self.source.execute('BEGIN')

    def target(self):
        return psycopg.connect(self.fixture.dsn, options=f'-c search_path={self.schema}')

    def drop_target(self):
        with psycopg.connect(self.fixture.dsn) as pg:
            pg.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def test_fork_imports_chat_and_shared_views_cannot_write(self):
        with self.target() as pg:
            result = fork_chat_preview(self.source, pg, self.fixture.schema)
        self.assertEqual((result['conversations'], result['messages']), (1, 1))
        with self.target() as pg:
            self.assertEqual(pg.execute('SELECT count(*) FROM chat_messages').fetchone()[0], 1)
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                pg.execute("DELETE FROM document_projection")
        with self.target() as pg, self.assertRaises(ValueError):
            fork_chat_preview(self.source, pg, self.fixture.schema)


    def test_deleted_chat_ids_are_not_reused(self):
        self.source.rollback()
        self.source.execute('PRAGMA query_only=OFF')
        self.source.execute('CREATE TABLE sequence_fixture(id INTEGER PRIMARY KEY AUTOINCREMENT)')
        self.source.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('conversations',82),('chat_messages',346)")
        self.source.commit()
        self.source.execute('PRAGMA query_only=ON')
        self.source.execute('BEGIN')
        with self.target() as pg:
            fork_chat_preview(self.source, pg, self.fixture.schema)
            cid=pg.execute("INSERT INTO conversations(channel) VALUES('web') RETURNING id").fetchone()[0]
            mid=pg.execute("INSERT INTO chat_messages(conversation_id,role,content) VALUES(%s,'user','test') RETURNING id",(cid,)).fetchone()[0]
            self.assertEqual((cid,mid),(83,347))


if __name__ == '__main__':
    unittest.main()
