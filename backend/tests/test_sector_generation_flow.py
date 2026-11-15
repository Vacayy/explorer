"""A real fixture replacement keeps a sector's document link on its old generation."""
import importlib.util
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql
from fastapi.testclient import TestClient

import database
from pipeline.postgres_snapshot import load_snapshot


@unittest.skipUnless(os.getenv('REFACTOR_TEST_DISPOSABLE') == '1', 'disposable fixture required')
class SectorGenerationFlow(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ['REFACTOR_POSTGRES_DSN']
        parts = psycopg.conninfo.conninfo_to_dict(self.dsn)
        if (parts.get('host'), parts.get('dbname'), parts.get('user')) != ('pg', 'fixture', 'fixture'):
            raise RuntimeError('Refusing non-fixture PostgreSQL')
        self.schema = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        with self.pg() as c:
            root = Path(__file__).resolve().parents[1] / 'refactor_sql'
            c.execute((root / 'document_projection.sql').read_text())
            c.execute((root / 'sector_market.sql').read_text())
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'source.sqlite'
        with patch.object(database, 'DB_PATH', self.path):
            database.init_db()
            c = database.get_connection()
            try:
                c.execute("INSERT INTO sector_map (sector_name, group_name) VALUES ('합성업종','합성섹터')")
                c.execute("INSERT INTO companies (corp_code, corp_name, stock_code, sector) VALUES ('c1','회사','000001','합성업종')")
                c.executemany('INSERT INTO stock_prices (stock_code,trade_date,close,market_cap) VALUES (?,?,?,?)',
                              [('000001','2025-09-01',100,1000), ('000001','2026-01-09',120,1200)])
                c.execute("INSERT INTO entities (id,type,name) VALUES (1,'sector','합성업종')")
                c.execute("INSERT INTO raw_documents (id,source_type,source_id,title,published_at,markdown) "
                          "VALUES (1,'blog','fixture','합성업종 문서','2026-01-09','첫 원문')")
                c.execute("INSERT INTO entity_links (doc_id,entity_id,link_type) VALUES (1,1,'industry')")
                c.commit()
            finally:
                c.close()
        script = Path(__file__).resolve().parents[2] / 'scripts/refactor_document_ui.py'
        with patch.dict(os.environ, {'REFACTOR_FIXTURE_SCHEMA': self.schema}):
            spec = importlib.util.spec_from_file_location('sector_generation_app', script)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.client = TestClient(module.app)

    def tearDown(self):
        self.tmp.cleanup()
        with psycopg.connect(self.dsn) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def pg(self):
        return psycopg.connect(self.dsn, options=f'-c search_path={self.schema}')

    def load(self, timestamp):
        source = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
        source.row_factory = sqlite3.Row
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        try:
            return load_snapshot(source, self.pg, snapshot_at=timestamp, include_sector=True,
                                 capacity_check=lambda *_: None)
        finally:
            source.close()

    def test_document_from_sector_keeps_original_after_replacement(self):
        self.load('2026-01-09T00:00:00+00:00')
        sector = self.client.get('/api/spine/industry/합성섹터')
        self.assertEqual(sector.status_code, 200)
        self.assertEqual([doc['id'] for doc in sector.json()['docs']], [1])
        generation = sector.headers['x-explorer-generation']
        current = self.client.get('/api/spine/doc/1', params={'generation': generation})
        self.assertEqual(current.json()['content'], '첫 원문')
        self.assertEqual(current.headers['x-explorer-archived'], '0')
        with sqlite3.connect(self.path) as c:
            c.execute("UPDATE raw_documents SET markdown='바뀐 원문' WHERE id=1")
        self.load('2026-01-10T00:00:00+00:00')
        previous = self.client.get('/api/spine/doc/1', params={'generation': generation})
        self.assertEqual(previous.status_code, 200)
        self.assertEqual(previous.json()['content'], '첫 원문')
        self.assertEqual(previous.headers['x-explorer-archived'], '1')
        self.assertEqual(self.client.get('/api/spine/doc/1').json()['content'], '바뀐 원문')
        with self.pg() as c:
            c.execute("UPDATE archived_timeline_generations SET expires_at=clock_timestamp()-interval '1 second' WHERE generation_id=%s", (generation,))
        self.assertEqual(self.client.get('/api/spine/doc/1', params={'generation': generation}).status_code, 410)
