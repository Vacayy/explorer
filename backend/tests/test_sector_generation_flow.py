"""A real fixture replacement keeps a sector's document link on its old generation."""
import importlib.util
import os
import sqlite3
import struct
import tempfile
import unittest
import uuid
from contextlib import closing
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
        self.media = Path(self.tmp.name) / 'media'
        (self.media / 'fixtures').mkdir(parents=True)
        (self.media / 'fixtures' / 'sample.jpg').write_bytes(b'old image bytes')
        with patch.object(database, 'DB_PATH', self.path):
            database.init_db()
            c = database.get_connection()
            try:
                c.execute("INSERT INTO sector_map (sector_name, group_name) VALUES ('합성업종','합성섹터')")
                c.execute("INSERT INTO companies (corp_code, corp_name, stock_code, sector) VALUES ('c1','회사','000001','합성업종')")
                c.executemany('INSERT INTO stock_prices (stock_code,trade_date,close,market_cap) VALUES (?,?,?,?)',
                              [('000001','2025-09-01',100,1000), ('000001','2026-01-09',120,1200)])
                c.execute("INSERT INTO entities (id,type,name) VALUES (1,'sector','합성업종')")
                c.execute("INSERT INTO blog_sources (url,platform,blog_name,is_active) VALUES ('https://example.test/','naver','fixture',1)")
                c.execute("INSERT INTO raw_documents (id,source_type,source_id,title,url,published_at,markdown,media_json) "
                          "VALUES (1,'blog','fixture','합성업종 문서','https://example.test/article','2026-01-09','첫 원문','[\"fixtures/sample.jpg\"]')")
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

    def load(self, timestamp, *, include_embeddings=False):
        source = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
        source.row_factory = sqlite3.Row
        if include_embeddings:
            import sqlite_vec
            source.enable_load_extension(True)
            sqlite_vec.load(source)
            source.enable_load_extension(False)
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        try:
            runtime = {
                'catalog': {'version': 'test', 'asOf': '2026-01-09', 'groups': [], 'companies': []},
                'prices': {'version': 'test', 'asOf': '2026-01-09', 'collectedAt': '2026-01-09T00:00:00Z',
                           'sourceUrl': 'https://example.com', 'sourceHash': 'a' * 64,
                           'field': 'regularMarketClosingPrice', 'session': 'KRX_REGULAR',
                           'adjustmentStatus': 'unverified', 'dates': ['2026-01-09'], 'prices': {},
                           'qualityIssues': [], 'caveats': []},
                'origin': 'collector', 'publishedAt': '2026-01-09T00:00:00Z', 'baselineOn': None,
                'lastAttempt': None, 'priceAgeDays': 0, 'snapshotAgeHours': 0,
                'signalStatus': 'held', 'signalHoldReason': 'fixture',
            }
            runtime = getattr(self, 'peer_runtime', runtime)
            return load_snapshot(source, self.pg, snapshot_at=timestamp, include_sector=True, media_root=self.media,
                                 peer_runtime=runtime, include_embeddings=include_embeddings,
                                 capacity_check=lambda *_: None)
        finally:
            source.close()

    def test_document_from_sector_keeps_original_after_replacement(self):
        self.load('2026-01-09T00:00:00+00:00')
        sector = self.client.get('/api/spine/industry/합성섹터')
        self.assertEqual(sector.status_code, 200)
        self.assertEqual([doc['id'] for doc in sector.json()['docs']], [1])
        generation = sector.headers['x-explorer-generation']
        timeline = self.client.get('/api/spine/feed/timeline', params={'generation': generation})
        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(timeline.headers['x-explorer-media-generation'], generation)
        self.assertTrue(any(item.get('document', {}).get('id') == 1 for item in timeline.json()['items'] if item.get('document')))
        current = self.client.get('/api/spine/doc/1', params={'generation': generation})
        self.assertEqual(current.json()['content'], '첫 원문')
        self.assertEqual(current.headers['x-explorer-archived'], '0')
        self.assertEqual(current.headers['x-explorer-media-generation'], generation)
        for url in ('/api/spine/industry/합성섹터/peers', '/api/peers/runtime'):
            peer = self.client.get(url, params={'generation': generation})
            self.assertEqual(peer.status_code, 200)
            self.assertEqual(peer.headers['x-explorer-generation'], generation)
        self.assertEqual(self.client.get(f'/api/refactor/media/{generation}/fixtures/sample.jpg').content, b'old image bytes')
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute("UPDATE raw_documents SET markdown='바뀐 원문' WHERE id=1")
        (self.media / 'fixtures' / 'sample.jpg').write_bytes(b'new image bytes')
        self.load('2026-01-10T00:00:00+00:00')
        timeline = self.client.get('/api/spine/feed/timeline', params={'generation': generation})
        self.assertEqual(timeline.status_code, 200)
        self.assertTrue(timeline.json()['archived'])
        self.assertEqual(timeline.headers['x-explorer-media-generation'], generation)
        for url in ('/api/spine/industry/합성섹터/peers', '/api/peers/runtime'):
            self.assertEqual(self.client.get(url, params={'generation': generation}).status_code, 410)
        previous = self.client.get('/api/spine/doc/1', params={'generation': generation})
        self.assertEqual(previous.status_code, 200)
        self.assertEqual(previous.json()['content'], '첫 원문')
        self.assertEqual(previous.headers['x-explorer-archived'], '1')
        self.assertEqual(previous.headers['x-explorer-media-generation'], generation)
        self.assertEqual(self.client.get(f'/api/refactor/media/{generation}/fixtures/sample.jpg').content, b'old image bytes')
        new_generation = self.client.get('/api/spine/industry/합성섹터').headers['x-explorer-generation']
        self.assertEqual(self.client.get(f'/api/refactor/media/{new_generation}/fixtures/sample.jpg').content, b'new image bytes')
        self.assertEqual(self.client.get('/api/spine/doc/1').json()['content'], '바뀐 원문')
        with self.pg() as c:
            c.execute("UPDATE archived_timeline_generations SET expires_at=clock_timestamp()-interval '1 second' WHERE generation_id=%s", (generation,))
        self.assertEqual(self.client.get('/api/spine/doc/1', params={'generation': generation}).status_code, 410)
        self.assertEqual(self.client.get(f'/api/refactor/media/{generation}/fixtures/sample.jpg').status_code, 410)
        self.load('2026-01-11T00:00:00+00:00')
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM media_blobs').fetchone()[0], 1)

    def test_unsafe_attachment_cannot_replace_a_valid_snapshot(self):
        self.load('2026-01-09T00:00:00+00:00')
        generation = self.client.get('/api/spine/industry/합성섹터').headers['x-explorer-generation']
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute("UPDATE raw_documents SET media_json='[\"../outside.jpg\"]' WHERE id=1")
        with self.assertRaises(ValueError):
            self.load('2026-01-10T00:00:00+00:00')
        self.assertEqual(self.client.get('/api/spine/industry/합성섹터').headers['x-explorer-generation'], generation)
        self.assertEqual(self.client.get(f'/api/refactor/media/{generation}/fixtures/sample.jpg').content, b'old image bytes')

    def test_embedding_snapshot_bytes_and_stale_generation_guard(self):
        import sqlite_vec
        from pipeline.postgres_embedding_snapshot import embedding_for_current_snapshot
        blob = struct.pack('<384f', *([0.25] * 384))
        with closing(sqlite3.connect(self.path)) as c, c:
            c.enable_load_extension(True)
            sqlite_vec.load(c)
            c.enable_load_extension(False)
            c.execute('CREATE VIRTUAL TABLE doc_vec USING vec0(embedding float[384])')
            c.execute('CREATE TABLE doc_vec_hash(rowid INTEGER PRIMARY KEY, content_hash TEXT)')
            c.execute('INSERT INTO doc_vec(rowid,embedding) VALUES (?,?)', (1, blob))
            c.execute('INSERT INTO doc_vec_hash(rowid,content_hash) VALUES (?,?)', (1, 'fixture-hash'))
        self.load('2026-01-09T00:00:00+00:00', include_embeddings=True)
        with self.pg() as c:
            self.assertEqual(embedding_for_current_snapshot(c, 1), (blob, 'fixture-hash'))
            self.assertIsNone(embedding_for_current_snapshot(c, 999))
            self.assertEqual(c.execute('SELECT vector_count, stale_count, source_hash_missing_count FROM document_embedding_metadata').fetchone(), (1, 0, 1))
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute("UPDATE raw_documents SET content_hash='changed-hash' WHERE id=1")
        self.load('2026-01-10T00:00:00+00:00', include_embeddings=True)
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT vector_count, stale_count, source_hash_missing_count FROM document_embedding_metadata').fetchone(), (1, 1, 0))
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('DELETE FROM doc_vec_hash WHERE rowid=1')
        with self.assertRaisesRegex(ValueError, 'Missing embedding hash'):
            self.load('2026-01-11T00:00:00+00:00', include_embeddings=True)
        with self.pg() as c:
            self.assertEqual(embedding_for_current_snapshot(c, 1), (blob, 'fixture-hash'))
        with closing(sqlite3.connect(self.path)) as c, c:
            c.enable_load_extension(True)
            sqlite_vec.load(c)
            c.enable_load_extension(False)
            c.execute('INSERT INTO doc_vec_hash(rowid,content_hash) VALUES (?,?)', (1, 'fixture-hash'))
            c.execute('DELETE FROM doc_vec WHERE rowid=1')
            c.execute('INSERT INTO doc_vec(rowid,embedding) VALUES (?,?)',
                      (1, struct.pack('<384f', float('nan'), *([0.0] * 383))))
        with self.assertRaisesRegex(ValueError, 'non-finite'):
            self.load('2026-01-11T00:00:00+00:00', include_embeddings=True)
        self.load('2026-01-11T00:00:00+00:00')
        with self.pg() as c:
            with self.assertRaisesRegex(ValueError, 'do not match'):
                embedding_for_current_snapshot(c, 1)

    def test_exact_vector_fixture_scan(self):
        import sqlite_vec
        from pipeline.postgres_embedding_snapshot import nearest_embeddings
        zero = struct.pack('<384f', *([0.0] * 384))
        one = struct.pack('<384f', *([1.0] * 384))
        with closing(sqlite3.connect(self.path)) as c, c:
            c.enable_load_extension(True)
            sqlite_vec.load(c)
            c.enable_load_extension(False)
            c.execute('CREATE VIRTUAL TABLE doc_vec USING vec0(embedding float[384])')
            c.execute('CREATE TABLE doc_vec_hash(rowid INTEGER PRIMARY KEY, content_hash TEXT)')
            c.execute("UPDATE raw_documents SET content_hash='h1' WHERE id=1")
            c.execute("INSERT INTO raw_documents (id,source_type,source_id,title,content_hash) VALUES (2,'note','two','two','h2')")
            c.executemany('INSERT INTO doc_vec(rowid,embedding) VALUES (?,?)', [(1, zero), (2, one)])
            c.executemany('INSERT INTO doc_vec_hash(rowid,content_hash) VALUES (?,?)', [(1, 'h1'), (2, 'h2')])
        self.load('2026-01-09T00:00:00+00:00', include_embeddings=True)
        with self.pg() as c:
            with self.assertRaisesRegex(ValueError, 'repeatable-read'):
                nearest_embeddings(c, zero)
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            found = nearest_embeddings(c, zero, limit=2)
            self.assertEqual([item[0] for item in found], [1, 2])
            self.assertEqual(found[0][1], 0.0)
            with self.assertRaises(ValueError):
                nearest_embeddings(c, b'bad')
