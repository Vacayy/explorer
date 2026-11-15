"""Synthetic snapshot replacement and rollback in a disposable PostgreSQL DB."""
import os
import json
import importlib.util
import sqlite3
import unittest
import uuid
import threading
import time
import tempfile
import subprocess
import sys
import struct
from datetime import date,datetime,timezone
from contextlib import closing
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

try:
    import psycopg
except ImportError:
    psycopg = None

from pipeline.postgres_document_read import PostgreSQLDocumentReader
from pipeline.postgres_snapshot import SNAPSHOT_LOCK_KEY, load_snapshot
from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader
from pipeline.postgres_rebuild_detail import rebuild_details
from pipeline.postgres_timeline_sources import PostgreSQLTimelineSources, GenerationExpired
from pipeline.postgres_rebuild_timeline import rebuild_source_timeline
from pipeline.postgres_rebuild_system_timeline import rebuild_system_timeline
from pipeline.postgres_capacity import require_snapshot_capacity, SnapshotCapacityError
from pipeline.postgres_archive_import_fixture import import_archived_documents
from pipeline.postgres_ingest_fixture import store_document, store_embedding, claim_enrichment, finish_enrichment
from pipeline.postgres_ledger_detail_fixture import LedgerDetailFixture
from pipeline.postgres_youtube_digest_fixture import queue as queue_video, finish as finish_video
from pipeline.postgres_ledger_snapshot_fixture import materialize
from pipeline.postgres_search_snapshot import SearchSnapshot
from pipeline.postgres_search_feed import search_feed
from pipeline.postgres_projection_copy_fixture import copy_projection, PROJECTION_TABLES
from pipeline.postgres_note_overlay_fixture import copy_with_note_changes
from pipeline.postgres_ingest_runner_fixture import embed_document, run_source
from pipeline.connectors.notes import NoteConnector
from pipeline.connectors.blog import BlogConnector
from pipeline.connectors.telegram import TelegramConnector
from pipeline.connectors.youtube import YouTubeConnector
from pipeline.postgres_link_preview_fixture import preview_links, prepare_enrichment, finish_with_links
from pipeline.postgres_graph_fixture import initialize_graph, finish_with_graph
from pipeline.postgres_enrich_worker_fixture import enrich_document
from pipeline.postgres_projection_publisher_fixture import FixturePublisher
from pipeline.postgres_signals_fixture import signals_items
from pipeline.postgres_signal_compute_fixture import compute_mention_signals
from pipeline.postgres_calendar_fixture import calendar_events
from pipeline.postgres_home_fixture import market_highlights, watchlist_updates
from pipeline.postgres_ingest_cycle_fixture import run_cycle, run_exclusive_cycle, run_periodic, CYCLE_LOCK
import tests.test_document_read_boundary as detail_fixtures


@unittest.skipUnless(psycopg and os.getenv('REFACTOR_POSTGRES_DSN') and
                     os.getenv('REFACTOR_TEST_DISPOSABLE') == '1',
                     'disposable isolated PostgreSQL fixture not configured')
class SnapshotReplacementTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ['REFACTOR_POSTGRES_DSN']
        target = psycopg.conninfo.conninfo_to_dict(self.dsn)
        if (target.get('host'), target.get('dbname'), target.get('user')) != ('pg', 'fixture', 'fixture'):
            raise RuntimeError('Refusing non-fixture PostgreSQL')
        self.schema = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(self.schema)))
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        self.fixture = detail_fixtures.DocumentReadBoundaryTests('test_raw_fallback_and_missing')
        self.fixture.setUp()
        with closing(self.fixture.connect()) as c:
            c.execute('ALTER TABLE raw_documents ADD COLUMN fetched_at TEXT')
            c.commit()
        self.reader = PostgreSQLDocumentReader(self.pg)

    def tearDown(self):
        self.fixture.tearDown()
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(self.schema)))

    def pg(self):
        return psycopg.connect(self.dsn, options=f'-c search_path={self.schema}')

    def load(self, at, *, include_linking=False, include_signals=False, include_events=False, include_centroids=False):
        source = sqlite3.connect(self.fixture.path.as_uri() + '?mode=ro', uri=True)
        source.row_factory = sqlite3.Row
        if include_centroids:
            import sqlite_vec
            source.enable_load_extension(True)
            try:
                sqlite_vec.load(source)
            finally:
                source.enable_load_extension(False)
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        try:
            with patch('pipeline.visibility.feed_mute_sql', return_value=('1=1', [])):
                return load_snapshot(source, self.pg, snapshot_at=at, capacity_check=lambda *_: None, include_linking=include_linking, include_signals=include_signals, include_events=include_events, include_centroids=include_centroids)
        finally:
            source.close()

    def test_centroids_load_with_the_same_snapshot_generation(self):
        import sqlite_vec
        with closing(self.fixture.connect()) as source:
            source.enable_load_extension(True)
            sqlite_vec.load(source)
            source.enable_load_extension(False)
            source.execute('CREATE VIRTUAL TABLE doc_centroid_vec USING vec0(embedding float[384])')
            vector=struct.pack('<384f',*([0.1]*384))
            source.execute('INSERT INTO doc_centroid_vec(rowid,embedding) VALUES (?,?)',(1,vector))
            source.commit()
        self.load('2026-01-03T00:00:00+00:00',include_centroids=True)
        from pipeline.postgres_related_documents import CentroidIndex
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            index=CentroidIndex.from_postgres(c)
            try:
                self.assertEqual(index.db.execute('SELECT count(*) FROM doc_centroid_vec').fetchone()[0],1)
            finally:
                index.close()

    def test_signal_snapshot_reads_existing_list_and_latest_theme(self):
        with self.fixture.connect() as c:
            c.execute('CREATE TABLE signals(id INTEGER,signal_type TEXT,entity_id INTEGER,date TEXT,payload_json TEXT,interpretation TEXT,interpretation_model TEXT)')
            c.execute("UPDATE raw_documents SET published_at='2099-01-01' WHERE id IN (1,2)")
            c.execute("INSERT INTO entity_links VALUES (2,7,'stock',0.8)")
            c.execute("INSERT INTO narratives VALUES (1,'합성 주제',1,'합성 내러티브','본문',3,'2026-01-01')")
            c.execute("INSERT INTO entities VALUES (8,'theme','합성 주제',NULL)")
            c.executemany('INSERT INTO signals VALUES (?,?,?,?,?,?,?)',[
                (1,'theme_surge',7,'2026-01-01','{}',None,None),
                (2,'theme_surge',7,'2026-01-02','{}',None,None),
                (3,'mention_surge',7,'2026-01-02','{}','기존 해석','fixture'),
                (4,'mention_surge',7,'2099-01-01','{}','미래 해석','fixture')])
        self.load('2026-01-03T00:00:00+00:00',include_signals=True)
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            self.assertEqual([item.id for item in signals_items(c,since='2026-01-01')],[4,3,2,1])
            self.assertEqual([item.id for item in signals_items(c,since='2026-01-01',signal_type='theme_surge')],[2])
            self.assertEqual(signals_items(c,since='2026-01-01',signal_type='mention_surge')[1].interpretation,'기존 해석')
            self.assertEqual([item.id for item in market_highlights(c,today=date(2026,1,3))],[4,3,2,1])
            updates=watchlist_updates(c,watched_codes={'000000'},follow_ids=[],since='2098-01-01',since_date='2098-01-01')
            self.assertEqual({row.doc_id for row in updates if row.kind=='document'},{1,2})
            self.assertEqual(len([row for row in updates if row.kind=='signal']),1)
        from fastapi.testclient import TestClient
        script=Path(__file__).resolve().parents[2]/'scripts/refactor_document_ui.py'
        with patch.dict(os.environ,{'REFACTOR_FIXTURE_SCHEMA':self.schema}):
            spec=importlib.util.spec_from_file_location('fixture_signal_ui',script)
            module=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with TestClient(module.app) as client:
                response=client.get('/api/spine/signals',params={'type':'mention_surge','days':7})
                self.assertEqual(response.status_code,200)
                self.assertEqual([row['id'] for row in response.json()['items']],[4])
                summary=client.get('/api/spine/signals/summary',params={'days':7})
                self.assertEqual(summary.status_code,200)
                self.assertEqual(summary.json()['as_of'],'2099-01-01')
                momentum=client.get('/api/spine/signals/momentum')
                self.assertEqual(momentum.status_code,200)
                self.assertEqual(momentum.json()['items'][0]['count_7d'],2)
                narratives=client.get('/api/spine/narrative/list')
                self.assertEqual(narratives.status_code,200)
                self.assertEqual(narratives.json()['items'][0]['title'],'합성 내러티브')
                narrative=client.get('/api/spine/narrative',params={'topic':'합성 주제'})
                self.assertEqual(narrative.status_code,200)
                self.assertEqual((narrative.json()['status'],narrative.json()['narrative']),('cached','본문'))

    def test_existing_mention_calculation_updates_isolated_snapshot(self):
        with self.fixture.connect() as c:
            c.execute('ALTER TABLE enrichments ADD COLUMN time_orientation TEXT')
            c.execute('CREATE TABLE signals(id INTEGER PRIMARY KEY,signal_type TEXT,entity_id INTEGER,date TEXT,payload_json TEXT,interpretation TEXT,interpretation_model TEXT, UNIQUE(signal_type,entity_id,date))')
            c.execute('DELETE FROM entity_links')
            for ident in (3,4,5):
                c.execute("INSERT INTO raw_documents VALUES (?,'blog',?,'합성 자료','https://example.test','2026-01-02','본문','본문',NULL,NULL,NULL)",(ident,f'new-{ident}'))
                c.execute("INSERT INTO entity_links VALUES (?,7,'stock',0.9)",(ident,))
        self.load('2026-01-03T00:00:00+00:00',include_signals=True)
        instant=datetime(2026,1,3,tzinfo=timezone.utc)
        with self.pg() as c:
            self.assertEqual(compute_mention_signals(c,as_of=instant),1)
            self.assertEqual(compute_mention_signals(c,as_of=instant),1)
            self.assertEqual(c.execute("SELECT count(*) FROM legacy_snapshot_rows WHERE table_name='signals'").fetchone()[0],1)
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            item=signals_items(c,since='2026-01-01',signal_type='mention_surge')[0]
            self.assertEqual(item.payload['count_7d'],3)

    def test_transcript_detail_and_quarters_use_snapshot(self):
        with self.fixture.connect() as c:
            c.execute('CREATE TABLE entity_keywords(entity_id INTEGER,keyword TEXT,status TEXT)')
            c.execute('CREATE TABLE entity_relations(id INTEGER,src_id INTEGER,dst_id INTEGER,rel_type TEXT,effect_direction TEXT,source_doc_id INTEGER)')
            c.execute("INSERT INTO transcripts VALUES (10,1,'TEST',2026,'Q1','저장된 정리','2026-01-01')")
            c.execute("INSERT INTO transcript_follow VALUES ('TEST','합성 기업',1)")
        self.load('2026-01-03T00:00:00+00:00',include_linking=True)
        from fastapi.testclient import TestClient
        script=Path(__file__).resolve().parents[2]/'scripts/refactor_document_ui.py'
        with patch.dict(os.environ,{'REFACTOR_FIXTURE_SCHEMA':self.schema}):
            spec=importlib.util.spec_from_file_location('fixture_transcript_ui',script)
            module=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with TestClient(module.app) as client:
                detail=client.get('/api/spine/transcript/detail/10')
                self.assertEqual(detail.status_code,200)
                self.assertEqual((detail.json()['digest'],detail.json()['body']),('저장된 정리','원문'))
                self.assertEqual(client.get('/api/spine/transcript/company/test').json()[0]['transcript_id'],10)
                self.assertEqual(client.get('/api/spine/transcript/detail/999').status_code,404)

    def test_event_snapshot_keeps_calendar_order_and_company(self):
        with self.fixture.connect() as c:
            c.execute('CREATE TABLE catalysts(id INTEGER,stock_code TEXT,corp_code TEXT,event_type TEXT,event_date TEXT,title TEXT)')
            c.execute('CREATE TABLE companies(corp_code TEXT,corp_name TEXT)')
            c.execute("INSERT INTO companies VALUES ('corp','합성 기업')")
            c.executemany('INSERT INTO catalysts VALUES (?,?,?,?,?,?)',[
                (1,'A','corp','schedule','2026-01-02','일정 A'),
                (2,'B',None,'schedule','2026-01-03','일정 B')])
        self.load('2026-01-03T00:00:00+00:00',include_events=True)
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            events=calendar_events(c,start=date(2026,1,1),watched_codes={'B'})
            self.assertEqual([row.id for row in events],[2,1])
            self.assertEqual(events[1].corp_name,'합성 기업')
            with self.assertRaisesRegex(ValueError,'Signal snapshot required'):
                signals_items(c,since='2026-01-01')

    def test_archive_to_ledger_preserves_source_and_rejects_second_import(self):
        self.load('2026-01-03T00:00:00+00:00')
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            with self.assertRaisesRegex(ValueError,'Embeddings are missing'):
                SearchSnapshot.from_postgres(c)
            index=SearchSnapshot.from_postgres(c,lexical_only=True)
            try:
                self.assertEqual(search_feed(c,index,'원문').items[0].id,1)
            finally:
                index.close()
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            self.assertEqual(import_archived_documents(c), 2)
            source_count = c.execute("SELECT count(*) FROM legacy_snapshot_rows WHERE table_name='raw_documents'").fetchone()[0]
            self.assertEqual(source_count, c.execute('SELECT count(*) FROM ingest_documents').fetchone()[0])
            self.assertIsNone(c.execute('SELECT summary FROM ingest_enrichments WHERE document_id=1').fetchone())
            self.assertEqual(c.execute('SELECT status FROM ingest_enrichment_jobs WHERE document_id=1').fetchone()[0], 'pending')
            row = store_document(c, source_type='note', source_id='new', title='new', markdown='synthetic')
            self.assertGreater(row['id'], 2)
        with self.assertRaisesRegex(ValueError, 'nonempty ledger'):
            with self.pg() as c:
                import_archived_documents(c)
        self.assertEqual(self.reader.list().total, 2)

    def test_import_preserves_legacy_display_but_only_current_hash_is_complete(self):
        with self.fixture.connect() as c:
            c.execute('ALTER TABLE raw_documents ADD COLUMN content_hash TEXT')
            c.execute('ALTER TABLE enrichments ADD COLUMN content_hash TEXT')
            c.execute("UPDATE raw_documents SET content_hash='current' WHERE id=1")
            c.execute("INSERT INTO enrichments(id,doc_id,summary,model,enriched_at,content_hash) "
                      "VALUES (3,1,'현재 원문의 요약','fixture','2026-02-01','current')")
            c.execute("INSERT INTO enrichments(id,doc_id,summary,model,enriched_at,content_hash) "
                      "VALUES (4,1,'나중의 오래된 요약','fixture','2026-03-01','stale')")
        self.load('2026-01-03T00:00:00+00:00')
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            self.assertEqual(c.execute('SELECT summary FROM ingest_enrichments WHERE document_id=1').fetchone()[0], '현재 원문의 요약')
            self.assertEqual(c.execute('SELECT status FROM ingest_enrichment_jobs WHERE document_id=1').fetchone()[0], 'done')
            self.assertEqual(c.execute('SELECT status FROM ingest_enrichment_jobs WHERE document_id=2').fetchone()[0], 'pending')
        self.assertEqual(self.reader.get(1).summary, '나중의 오래된 요약')

    def test_existing_linker_preview_rejects_graph_side_effects(self):
        with self.fixture.connect() as c:
            c.execute('CREATE TABLE entity_keywords(entity_id INTEGER,keyword TEXT,status TEXT)')
            c.execute('CREATE TABLE entity_relations(src_id INTEGER,dst_id INTEGER,rel_type TEXT,epistemic_type TEXT,confidence REAL,source_doc_id INTEGER,valid_from TEXT)')
            c.execute("INSERT INTO entity_keywords VALUES (7,'다른별명','active')")
            c.execute("INSERT INTO entities VALUES (8,'sector','산업A',NULL)")
            c.execute("INSERT INTO entities VALUES (9,'theme','주제B',NULL)")
        self.load('2026-01-03T00:00:00+00:00',include_linking=True)
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            doc=store_document(c,source_type='note',source_id='link-fixture',title='자료',markdown='합성 회사 문서')
            claim=claim_enrichment(c,document_id=doc['id'])
            claim_enrichment(c,document_id=1)
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            out=preview_links(c,doc['id'],{'stocks':['합성 회사'],'industries':[],'topics':[]})
            self.assertEqual(out['links'],[{'entity_id':7,'link_type':'stock','confidence':0.9}])
            self.assertEqual(out['legacy_links_replaced'],0)
            old=preview_links(c,1,{'stocks':['합성 회사'],'industries':[],'topics':[]})
            self.assertEqual(old['legacy_links_replaced'],1)
            prepared=prepare_enrichment(c,doc['id'],claim['token'],{'stocks':['합성 회사'],'industries':[],'topics':[]})
            for result in (
                {'stocks':[],'industries':['새 산업'],'topics':[]},
                {'stocks':['합성 회사'],'stock_aliases':[{'name':'합성 회사','alias':'새별명'}],'industries':[],'topics':[]},
                {'stocks':[],'industries':['산업A'],'topics':['주제B'],'label_parents':{'산업A':'주제B'}},
            ):
                with self.subTest(result=result),self.assertRaisesRegex(ValueError,'side effect'):
                    preview_links(c,doc['id'],result)
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with self.pg() as c:
                finish_with_links(c,doc['id'],revision=prepared['revision'],token=prepared['token'],
                                  summary='합성 요약',model='fixture',links=prepared['links']*2)
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT status FROM ingest_enrichment_jobs WHERE document_id=%s',(doc['id'],)).fetchone()[0],'running')
            self.assertIsNone(c.execute('SELECT summary FROM ingest_enrichments WHERE document_id=%s',(doc['id'],)).fetchone())
            self.assertTrue(finish_with_links(c,doc['id'],summary='합성 요약',model='fixture',**prepared))
            self.assertEqual(c.execute('SELECT count(*) FROM ingest_entity_links WHERE document_id=%s',(doc['id'],)).fetchone()[0],1)
            store_document(c,source_type='note',source_id='link-fixture',title='자료',markdown='새 내용')
            self.assertFalse(finish_with_links(c,doc['id'],summary='늦은 요약',model='fixture',**prepared))

    def test_existing_linker_result_reaches_detail_filter_and_search(self):
        with self.fixture.connect() as c:
            c.execute('CREATE TABLE entity_keywords(entity_id INTEGER,keyword TEXT,status TEXT)')
            c.execute('CREATE TABLE entity_relations(src_id INTEGER,dst_id INTEGER,rel_type TEXT,epistemic_type TEXT,confidence REAL,source_doc_id INTEGER,valid_from TEXT)')
        self.load('2026-01-03T00:00:00+00:00',include_linking=True)
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            doc=store_document(c,source_type='note',source_id='link-new',title='합성 회사',markdown='합성 회사에 관한 신규 문서')
            claim=claim_enrichment(c,document_id=doc['id'])
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            prepared=prepare_enrichment(c,doc['id'],claim['token'],{'stocks':['합성 회사'],'industries':[],'topics':[]})
        with self.pg() as c:
            self.assertTrue(finish_with_links(c,doc['id'],summary='신규 요약',model='fixture',**prepared))
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        reader=PostgreSQLDocumentReader(target)
        self.assertEqual([(e.entity_id,e.link_type) for e in reader.get(doc['id']).entities],[(7,'stock')])
        self.assertIn(doc['id'],[item.id for item in reader.list(stock='000000').items])
        with target() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            generation=c.execute('SELECT generation_id FROM snapshot_metadata').fetchone()[0]
            rows=c.execute("SELECT (row_data->>'id')::bigint,row_data->>'title',row_data->>'markdown' "
                           "FROM legacy_snapshot_rows WHERE table_name='raw_documents' ORDER BY row_ordinal").fetchall()
            index=SearchSnapshot(generation,rows)
            try:
                self.assertIn(doc['id'],[item.id for item in search_feed(c,index,'신규',stock='000000').items])
            finally:
                index.close()

    def test_graph_side_effects_are_atomic_and_preserved(self):
        with self.fixture.connect() as c:
            c.execute('ALTER TABLE entities ADD COLUMN meta_json TEXT')
            c.execute('ALTER TABLE entities ADD COLUMN created_at TEXT')
            c.execute("UPDATE entities SET meta_json=? WHERE id=7", ('{\"fixture_metadata\":\"preserve\"}',))
            c.execute('CREATE TABLE entity_keywords(id INTEGER PRIMARY KEY,entity_id INTEGER,keyword TEXT,status TEXT,created_at TEXT)')
            c.execute('CREATE TABLE entity_relations(id INTEGER PRIMARY KEY,src_id INTEGER,dst_id INTEGER,rel_type TEXT,epistemic_type TEXT,confidence REAL,source_doc_id INTEGER,valid_from TEXT,mechanism TEXT,created_at TEXT)')
            c.execute("INSERT INTO entity_relations VALUES (3,7,7,'fixture','fact',0.9,1,NULL,'기존 관계 설명',NULL)")
        self.load('2026-01-03T00:00:00+00:00',include_linking=True)
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            initialize_graph(c)
            doc=store_document(c,source_type='note',source_id='graph-new',title='합성 회사',markdown='합성 회사 자료')
            claim=claim_enrichment(c,document_id=doc['id'])
        result={'stocks':['합성 회사'],'stock_aliases':[{'name':'합성 회사','alias':'새별명'}],
                'industries':['신규 산업'],'topics':['신규 주제'],'label_parents':{'신규 산업':'신규 주제'}}
        with self.assertRaisesRegex(RuntimeError,'fixture failure'):
            with self.pg() as c, patch('pipeline.postgres_graph_fixture.finish_enrichment',side_effect=RuntimeError('fixture failure')):
                finish_with_graph(c,doc['id'],revision=claim['revision'],token=claim['token'],summary='요약',model='fixture',result=result)
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM ingest_graph_entities').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM ingest_graph_keywords').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT status FROM ingest_enrichment_jobs WHERE document_id=%s',(doc['id'],)).fetchone()[0],'running')
            self.assertTrue(finish_with_graph(c,doc['id'],revision=claim['revision'],token=claim['token'],summary='요약',model='fixture',result=result))
            self.assertEqual(c.execute('SELECT count(*) FROM ingest_graph_entities').fetchone()[0],3)
            self.assertEqual(c.execute("SELECT status FROM ingest_graph_keywords WHERE keyword='새별명'").fetchone()[0],'proposed')
            self.assertEqual(c.execute("SELECT count(*) FROM ingest_graph_relations WHERE rel_type='MEMBER_OF'").fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM ingest_entity_links WHERE document_id=%s',(doc['id'],)).fetchone()[0],3)
            self.assertEqual(c.execute("SELECT count(*) FROM legacy_snapshot_rows WHERE table_name='entities'").fetchone()[0],1)
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        reader=PostgreSQLDocumentReader(target)
        detail=reader.get(doc['id'])
        self.assertEqual({e.name for e in detail.entities},{'합성 회사','신규 산업','신규 주제'})
        self.assertIn(doc['id'],[item.id for item in reader.list(industry='신규 산업').items])
        self.assertIn(doc['id'],[item.id for item in reader.list(topic='신규 주제').items])
        with target() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM legacy_snapshot_rows WHERE table_name='entity_keywords' AND row_data->>'keyword'='새별명' AND row_data->>'status'='proposed'").fetchone()[0],1)
            self.assertEqual(c.execute("SELECT count(*) FROM legacy_snapshot_rows WHERE table_name='entity_relations' AND row_data->>'rel_type'='MEMBER_OF'").fetchone()[0],1)
            self.assertEqual(c.execute("SELECT row_data->>'mechanism' FROM legacy_snapshot_rows WHERE table_name='entity_relations' AND row_data->>'rel_type'='fixture'").fetchone()[0],'기존 관계 설명')
            self.assertEqual(c.execute("SELECT row_data->>'meta_json' FROM legacy_snapshot_rows WHERE table_name='entities' AND row_data->>'id'='7'").fetchone()[0],'{"fixture_metadata":"preserve"}')
            keyword=c.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entity_keywords' AND row_data->>'keyword'='새별명'").fetchone()[0]
            relation=c.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entity_relations' AND row_data->>'rel_type'='MEMBER_OF'").fetchone()[0]
            self.assertIsInstance(keyword['id'],int)
            self.assertTrue(keyword['created_at'])
            self.assertGreater(relation['id'],3)
            self.assertTrue(relation['created_at'])
            self.assertIsNone(relation['mechanism'])
        # A future schema default must not silently become NULL in new rows.
        with self.pg() as c:
            c.execute("UPDATE legacy_snapshot_tables SET columns=columns || '[\"new_default\"]'::jsonb, "
                      "schema_sql=replace(schema_sql, ')', ', new_default TEXT DEFAULT ''required'')') "
                      "WHERE table_name='entity_keywords'")
        rejected='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(rejected)))
        def cleanup_rejected():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(rejected)))
        self.addCleanup(cleanup_rejected)
        with psycopg.connect(self.dsn,options=f'-c search_path={rejected}') as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.assertRaisesRegex(ValueError,'Unsupported default for graph field entity_keywords.new_default'):
            with self.pg() as c:
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                copy_with_note_changes(c,self.schema,rejected)

    def test_note_connector_to_enrichment_graph_and_search(self):
        with self.fixture.connect() as c:
            c.execute('CREATE TABLE entity_keywords(entity_id INTEGER,keyword TEXT,status TEXT)')
            c.execute('CREATE TABLE entity_relations(src_id INTEGER,dst_id INTEGER,rel_type TEXT,epistemic_type TEXT,confidence REAL,source_doc_id INTEGER,valid_from TEXT)')
        self.load('2026-01-03T00:00:00+00:00',include_linking=True)
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            initialize_graph(c)
        with tempfile.TemporaryDirectory() as vault:
            notes=Path(vault)/'notes'
            notes.mkdir()
            (notes/'fixture.md').write_text('# 수집 연결 시험\n\n검색용 신규 본문',encoding='utf-8')
            stats=run_source(NoteConnector(Path(vault)),self.pg)
            self.assertEqual((stats['docs'],stats['new']),(1,1))
            self.assertEqual(run_source(NoteConnector(Path(vault)),self.pg)['unchanged'],1)
        post={'title':'합성 블로그','url':'https://example.test/new-post',
              'published_at':'2026-01-02T00:00:00Z','content':'블로그 본문 검색어 ' * 80}
        with patch('pipeline.connectors.blog.detect_platform_and_feed_url',return_value=('fixture',None)), \
                patch('pipeline.connectors.blog.scrape_rss',return_value=([post],'합성 채널')):
            self.assertEqual(run_source(BlogConnector(['https://example.test/']),self.pg)['new'],1)
            self.assertEqual(run_source(BlogConnector(['https://example.test/']),self.pg)['unchanged'],1)
        with self.pg() as c:
            ident=c.execute("SELECT id FROM ingest_documents WHERE source_type='note' AND source_id='fixture.md'").fetchone()[0]
            blog_id=c.execute("SELECT id FROM ingest_documents WHERE source_type='blog' AND source_id=%s",(post['url'],)).fetchone()[0]
        def failed(*_):
            raise RuntimeError('fixture error')
        with self.assertRaisesRegex(RuntimeError,'fixture error'):
            enrich_document(self.pg,ident,enrich=failed)
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT status FROM ingest_enrichment_jobs WHERE document_id=%s',(ident,)).fetchone()[0],'failed')
        def synthetic(title,markdown):
            self.assertEqual(title,'수집 연결 시험')
            self.assertIn('신규 본문',markdown)
            return {'summary':'합성 요약','model':'fixture','sentiment':'positive','time_orientation':'forward',
                    'reference_period':'2027','stocks':[],'industries':['연결 산업'],'topics':[]}
        self.assertTrue(enrich_document(self.pg,ident,enrich=synthetic))
        self.assertFalse(enrich_document(self.pg,ident,enrich=synthetic))
        from pipeline.enrich import _enrich_keyword
        self.assertTrue(enrich_document(self.pg,blog_id,enrich=_enrich_keyword))
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        reader=PostgreSQLDocumentReader(target)
        detail=reader.get(ident)
        self.assertEqual((detail.title,detail.summary),('수집 연결 시험','합성 요약'))
        self.assertIn(ident,[item.id for item in reader.list(industry='연결 산업').items])
        self.assertEqual(reader.get(blog_id).title,'합성 블로그')
        with target() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            fields=c.execute("SELECT row_data->>'sentiment',row_data->>'time_orientation',row_data->>'reference_period' "
                             "FROM legacy_snapshot_rows WHERE table_name='enrichments' AND row_data->>'doc_id'=%s",(str(ident),)).fetchone()
            self.assertEqual(fields,('positive','forward','2027'))
            generation=c.execute('SELECT generation_id FROM snapshot_metadata').fetchone()[0]
            rows=c.execute("SELECT (row_data->>'id')::bigint,row_data->>'title',row_data->>'markdown' "
                           "FROM legacy_snapshot_rows WHERE table_name='raw_documents' ORDER BY row_ordinal").fetchall()
            index=SearchSnapshot(generation,rows)
            try:
                self.assertIn(ident,[item.id for item in search_feed(c,index,'신규',industry='연결 산업').items])
                self.assertIn(blog_id,[item.id for item in search_feed(c,index,'검색어').items])
            finally:
                index.close()

    def test_collection_cycle_processes_only_changed_documents(self):
        with self.fixture.connect() as c:
            c.execute('CREATE TABLE entity_keywords(entity_id INTEGER,keyword TEXT,status TEXT)')
            c.execute('CREATE TABLE entity_relations(src_id INTEGER,dst_id INTEGER,rel_type TEXT,epistemic_type TEXT,confidence REAL,source_doc_id INTEGER,valid_from TEXT)')
        self.load('2026-01-03T00:00:00+00:00',include_linking=True)
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            initialize_graph(c)
        with tempfile.TemporaryDirectory() as vault:
            notes=Path(vault)/'notes'
            notes.mkdir()
            note=notes/'cycle.md'
            note.write_text('# 합성 문서\n본문',encoding='utf-8')
            from pipeline.enrich import _enrich_keyword
            first=run_cycle(NoteConnector(Path(vault)),self.pg,enrich=_enrich_keyword)
            second=run_cycle(NoteConnector(Path(vault)),self.pg,enrich=_enrich_keyword)
            note.write_text('# 합성 문서\n변경된 본문',encoding='utf-8')
            def failed(*_):
                raise RuntimeError('fixture failure')
            third=run_cycle(NoteConnector(Path(vault)),self.pg,enrich=failed)
            fourth=run_cycle(NoteConnector(Path(vault)),self.pg,enrich=_enrich_keyword)
            (notes/'abandoned.md').write_text('# 복구 자료\n원문',encoding='utf-8')
            with self.pg() as c:
                abandoned=store_document(c,source_type='note',source_id='abandoned.md',title='복구 자료',markdown='# 복구 자료\n원문')
                old_claim=claim_enrichment(c,document_id=abandoned['id'],worker_id='cycle:stopped')
                other=store_document(c,source_type='note',source_id='other.md',title='별도 작업',markdown='본문')
                claim_enrichment(c,document_id=other['id'],worker_id='other-worker')
            recovered=run_exclusive_cycle(NoteConnector(Path(vault)),self.pg,enrich=_enrich_keyword)
            with self.pg() as c:
                self.assertFalse(finish_enrichment(c,document_id=abandoned['id'],**old_claim,summary='늦은 결과',model='fixture'))
                self.assertEqual(c.execute('SELECT status FROM ingest_enrichment_jobs WHERE document_id=%s',(other['id'],)).fetchone()[0],'running')
            with self.pg() as lease:
                lease.execute('SELECT pg_advisory_lock(%s)',(CYCLE_LOCK,))
                with self.assertRaisesRegex(RuntimeError,'Another fixture cycle is running'):
                    run_exclusive_cycle(NoteConnector(Path(vault)),self.pg,enrich=_enrich_keyword)
                lease.execute('SELECT pg_advisory_unlock(%s)',(CYCLE_LOCK,))
        self.assertEqual((first['new'],first['enriched']), (1,1))
        self.assertEqual((second['unchanged'],second['enriched']), (1,0))
        self.assertEqual((third['updated'],third['enrichment_failed']), (1,1))
        self.assertEqual((fourth['unchanged'],fourth['enriched']), (1,1))
        self.assertEqual(recovered['enriched'],1)
        with self.pg() as c:
            self.assertEqual(c.execute("SELECT e.summary FROM ingest_enrichments e JOIN ingest_documents d ON d.id=e.document_id WHERE d.source_id='cycle.md'").fetchone()[0], '# 합성 문서 변경된 본문')
            ident=c.execute("SELECT id FROM ingest_documents WHERE source_type='note' AND source_id='cycle.md'").fetchone()[0]
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        self.assertEqual(PostgreSQLDocumentReader(target).get(ident).summary,'# 합성 문서 변경된 본문')

    def test_exclusive_cycle_recovers_after_process_exit(self):
        with self.fixture.connect() as c:
            c.execute('CREATE TABLE entity_keywords(entity_id INTEGER,keyword TEXT,status TEXT)')
            c.execute('CREATE TABLE entity_relations(src_id INTEGER,dst_id INTEGER,rel_type TEXT,epistemic_type TEXT,confidence REAL,source_doc_id INTEGER,valid_from TEXT)')
        self.load('2026-01-03T00:00:00+00:00',include_linking=True)
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            initialize_graph(c)
        code='''import os,psycopg
from pathlib import Path
from pipeline.connectors.notes import NoteConnector
from pipeline.postgres_ingest_cycle_fixture import run_exclusive_cycle
def factory():
    return psycopg.connect(os.environ['REFACTOR_POSTGRES_DSN'],options='-c search_path='+os.environ['FIXTURE_SCHEMA'])
def terminate(*args):
    os._exit(23)
run_exclusive_cycle(NoteConnector(Path(os.environ['FIXTURE_VAULT'])),factory,enrich=terminate)
'''
        with tempfile.TemporaryDirectory() as vault:
            notes=Path(vault)/'notes'
            notes.mkdir()
            (notes/'crash.md').write_text('# 복구 문서\n원문',encoding='utf-8')
            env={**os.environ,'FIXTURE_SCHEMA':self.schema,'FIXTURE_VAULT':vault}
            child=subprocess.run([sys.executable,'-c',code],env=env,timeout=15,capture_output=True)
            self.assertEqual(child.returncode,23)
            with self.pg() as c:
                self.assertEqual(c.execute("SELECT j.status FROM ingest_enrichment_jobs j JOIN ingest_documents d ON d.id=j.document_id WHERE d.source_id='crash.md'").fetchone()[0],'running')
            from pipeline.enrich import _enrich_keyword
            recovered=run_exclusive_cycle(NoteConnector(Path(vault)),self.pg,enrich=_enrich_keyword)
            self.assertEqual((recovered['unchanged'],recovered['enriched']),(1,1))
            with self.pg() as c:
                self.assertEqual(c.execute("SELECT j.status FROM ingest_enrichment_jobs j JOIN ingest_documents d ON d.id=j.document_id WHERE d.source_id='crash.md'").fetchone()[0],'done')

    def test_periodic_fixture_runs_changed_note_twice(self):
        with self.fixture.connect() as c:
            c.execute('CREATE TABLE entity_keywords(entity_id INTEGER,keyword TEXT,status TEXT)')
            c.execute('CREATE TABLE entity_relations(src_id INTEGER,dst_id INTEGER,rel_type TEXT,epistemic_type TEXT,confidence REAL,source_doc_id INTEGER,valid_from TEXT)')
            c.execute('ALTER TABLE enrichments ADD COLUMN time_orientation TEXT')
            c.execute('CREATE TABLE signals(id INTEGER PRIMARY KEY,signal_type TEXT,entity_id INTEGER,date TEXT,payload_json TEXT,interpretation TEXT,interpretation_model TEXT,UNIQUE(signal_type,entity_id,date))')
        self.load('2026-01-03T00:00:00+00:00',include_linking=True,include_signals=True)
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            initialize_graph(c)
        with tempfile.TemporaryDirectory() as vault:
            notes=Path(vault)/'notes'
            notes.mkdir()
            note=notes/'periodic.md'
            note.write_text('# 정기 문서\n처음',encoding='utf-8')
            stop=threading.Event()
            results=[]
            errors=[]
            computed=[]
            def process_projection(conn):
                computed.append(compute_mention_signals(conn,as_of=datetime(2026,1,3,tzinfo=timezone.utc)))
            publisher=FixturePublisher(self.pg,self.schema,lambda schema:psycopg.connect(self.dsn,options=f'-c search_path={schema}'),process_projection=process_projection)
            self.addCleanup(publisher.close)
            observed=[]
            observed_ids=[]
            def completed(result):
                results.append(result)
                publisher.publish()
                with self.pg() as c:
                    ident=c.execute("SELECT id FROM ingest_documents WHERE source_type='note' AND source_id='periodic.md'").fetchone()[0]
                observed_ids.append(ident)
                observed.append(publisher.get(ident).summary)
                if len(results)==1:
                    note.write_text('# 정기 문서\n변경',encoding='utf-8')
                else:
                    stop.set()
            from pipeline.enrich import _enrich_keyword
            def connector():
                if not errors:
                    raise RuntimeError('fixture transient error')
                return NoteConnector(Path(vault))
            run_periodic(connector,self.pg,enrich=_enrich_keyword,
                         stop=stop,interval_seconds=0.01,on_cycle=completed,on_error=errors.append)
            self.assertEqual(len(errors),1)
            self.assertEqual(computed,[0,0])
            self.assertEqual(observed,['# 정기 문서 처음','# 정기 문서 변경'])
            ident=observed_ids[-1]
            self.assertIn(ident,[row.id for row in publisher.search('변경').items])
            def broken_index(*_):
                raise RuntimeError('fixture index failure')
            publisher.index_factory=broken_index
            with self.assertRaisesRegex(RuntimeError,'fixture index failure'):
                publisher.publish()
            self.assertEqual(publisher.get(ident).summary,'# 정기 문서 변경')
            self.assertIn(ident,[row.id for row in publisher.search('변경').items])
            publisher.index_factory=SearchSnapshot
            with patch.object(publisher,'_drop',side_effect=RuntimeError('cleanup failure')):
                publisher.publish()
                self.assertEqual(len(publisher.pending_cleanup),1)
                self.assertEqual(publisher.get(ident).summary,'# 정기 문서 변경')
                with self.assertRaisesRegex(RuntimeError,'cleanup failure'):
                    publisher.publish()
            publisher.cleanup_retired()
            self.assertFalse(publisher.pending_cleanup)
            publisher.close()
        self.assertEqual([(r['new'],r['updated'],r['enriched']) for r in results],[(1,0,1),(0,1,1)])
        with self.pg() as c:
            self.assertEqual(c.execute("SELECT e.summary FROM ingest_enrichments e JOIN ingest_documents d ON d.id=e.document_id WHERE d.source_id='periodic.md'").fetchone()[0],'# 정기 문서 변경')
            ident=c.execute("SELECT id FROM ingest_documents WHERE source_type='note' AND source_id='periodic.md'").fetchone()[0]
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        self.assertEqual(PostgreSQLDocumentReader(target).get(ident).summary,'# 정기 문서 변경')

    def test_telegram_connector_collects_and_enriches_without_network(self):
        with self.fixture.connect() as c:
            c.execute('CREATE TABLE entity_keywords(entity_id INTEGER,keyword TEXT,status TEXT)')
            c.execute('CREATE TABLE entity_relations(src_id INTEGER,dst_id INTEGER,rel_type TEXT,epistemic_type TEXT,confidence REAL,source_doc_id INTEGER,valid_from TEXT)')
            c.execute("INSERT INTO telegram_channels VALUES ('fixture','합성 채널',1)")
            c.execute("INSERT INTO telegram_channels VALUES ('muted','숨김 채널',0)")
        self.load('2026-01-03T00:00:00+00:00',include_linking=True)
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            initialize_graph(c)
        message={'message_id':'123','content':'합성 텔레그램 수집 본문',
                 'date':'2026-01-02T00:00:00Z','link':'https://t.me/fixture/123','images':[]}
        with patch('pipeline.connectors.telegram.scrape_channel',return_value=[message]), \
                patch('pipeline.connectors.telegram.image_reading.read_images',return_value={}):
            self.assertEqual(run_source(TelegramConnector(['fixture']),self.pg)['new'],1)
            self.assertEqual(run_source(TelegramConnector(['fixture']),self.pg)['unchanged'],1)
            self.assertEqual(run_source(TelegramConnector(['muted']),self.pg)['new'],1)
        with self.pg() as c:
            ident=c.execute("SELECT id FROM ingest_documents WHERE source_type='telegram' AND source_id='fixture/123'").fetchone()[0]
            muted_id=c.execute("SELECT id FROM ingest_documents WHERE source_type='telegram' AND source_id='muted/123'").fetchone()[0]
        from pipeline.enrich import _enrich_keyword
        self.assertTrue(enrich_document(self.pg,ident,enrich=_enrich_keyword))
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT summary,model FROM ingest_enrichments WHERE document_id=%s',(ident,)).fetchone(),
                             ('합성 텔레그램 수집 본문','keyword'))
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        reader=PostgreSQLDocumentReader(target)
        self.assertEqual(reader.get(ident).summary,'합성 텔레그램 수집 본문')
        self.assertIn(ident,[row.id for row in reader.list(source='telegram').items])
        self.assertNotIn(muted_id,[row.id for row in reader.list(source='telegram').items])
        with target() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            self.assertEqual(c.execute('SELECT channel FROM timeline_source_projection WHERE document_id=%s',(ident,)).fetchone()[0],'telegram:fixture')
            self.assertIsNone(c.execute('SELECT channel FROM timeline_source_projection WHERE document_id=%s',(muted_id,)).fetchone())
            generation=c.execute('SELECT generation_id FROM snapshot_metadata').fetchone()[0]
            rows=c.execute("SELECT (row_data->>'id')::bigint,row_data->>'title',row_data->>'markdown' "
                           "FROM legacy_snapshot_rows WHERE table_name='raw_documents' ORDER BY row_ordinal").fetchall()
            index=SearchSnapshot(generation,rows)
            try:
                self.assertIn(ident,[row.id for row in search_feed(c,index,'텔레그램',source='telegram').items])
            finally:
                index.close()

    def test_youtube_connector_to_detail_and_search_without_network(self):
        with self.fixture.connect() as c:
            c.execute('CREATE TABLE entity_keywords(entity_id INTEGER,keyword TEXT,status TEXT)')
            c.execute('CREATE TABLE entity_relations(src_id INTEGER,dst_id INTEGER,rel_type TEXT,epistemic_type TEXT,confidence REAL,source_doc_id INTEGER,valid_from TEXT)')
            c.execute("INSERT INTO youtube_channels VALUES ('UCfixture','합성 영상 채널',1)")
        self.load('2026-01-03T00:00:00+00:00',include_linking=True)
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            initialize_graph(c)
        with patch('pipeline.connectors.youtube.fetch_transcript',return_value='합성 영상 자막과 검색어'), \
             patch('pipeline.connectors.youtube._video_title',return_value='합성 영상'), \
             patch('pipeline.connectors.youtube._video_published',return_value='2026-01-02T00:00:00Z'), \
             patch('pipeline.connectors.youtube.video_channel_id',return_value='UCfixture'):
            self.assertEqual(run_source(YouTubeConnector(video_ids=['abc123def45']),self.pg)['new'],1)
            self.assertEqual(run_source(YouTubeConnector(video_ids=['abc123def45']),self.pg)['unchanged'],1)
        with self.pg() as c:
            ident=c.execute("SELECT id FROM ingest_documents WHERE source_type='youtube' AND source_id='UCfixture/abc123def45'").fetchone()[0]
            self.assertEqual(c.execute('SELECT raw_content,digest_status FROM ingest_documents WHERE id=%s',(ident,)).fetchone(),('합성 영상 자막과 검색어','pending'))
        from pipeline.enrich import _enrich_keyword
        self.assertTrue(enrich_document(self.pg,ident,enrich=_enrich_keyword))
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        reader=PostgreSQLDocumentReader(target)
        detail=reader.get(ident)
        self.assertEqual((detail.title,detail.summary,detail.content),('합성 영상','합성 영상 자막과 검색어','합성 영상 자막과 검색어'))
        self.assertIn(ident,[row.id for row in reader.list(source='youtube').items])
        with target() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            generation=c.execute('SELECT generation_id FROM snapshot_metadata').fetchone()[0]
            rows=c.execute("SELECT (row_data->>'id')::bigint,row_data->>'title',row_data->>'markdown' "
                           "FROM legacy_snapshot_rows WHERE table_name='raw_documents' ORDER BY row_ordinal").fetchall()
            index=SearchSnapshot(generation,rows)
            try:
                self.assertIn(ident,[row.id for row in search_feed(c,index,'검색어',source='youtube').items])
            finally:
                index.close()

    def test_concurrent_new_graph_names_share_one_entity(self):
        from concurrent.futures import ThreadPoolExecutor
        with self.fixture.connect() as c:
            c.execute('CREATE TABLE entity_keywords(entity_id INTEGER,keyword TEXT,status TEXT)')
            c.execute('CREATE TABLE entity_relations(src_id INTEGER,dst_id INTEGER,rel_type TEXT,epistemic_type TEXT,confidence REAL,source_doc_id INTEGER,valid_from TEXT)')
        self.load('2026-01-03T00:00:00+00:00',include_linking=True)
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            initialize_graph(c)
            docs=[]
            for number in range(2):
                doc=store_document(c,source_type='note',source_id=f'graph-{number}',title='자료',markdown='본문')
                claim=claim_enrichment(c,document_id=doc['id'])
                docs.append((doc,claim))
        barrier=threading.Barrier(2)
        def worker(pair):
            doc,claim=pair
            barrier.wait(timeout=5)
            with self.pg() as c:
                return finish_with_graph(c,doc['id'],revision=claim['revision'],token=claim['token'],
                                         summary='요약',model='fixture',result={'stocks':[],'industries':['동일 산업'],'topics':[]})
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(worker,docs)),[True,True])
        with self.pg() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM ingest_graph_entities WHERE type='sector' AND name='동일 산업'").fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(DISTINCT entity_id) FROM ingest_entity_links WHERE document_id=ANY(%s)',
                                       ([doc['id'] for doc,_ in docs],)).fetchone()[0],1)
        with self.assertRaisesRegex(ValueError, 'read committed'):
            with self.pg() as c:
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                doc, claim = docs[0]
                finish_with_graph(c,doc['id'],revision=claim['revision'],token=claim['token'],
                                  summary='요약',model='fixture',result={})

    def test_ledger_detail_keeps_legacy_links_and_suppresses_stale_links(self):
        self.load('2026-01-03T00:00:00+00:00')
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
        ledger_reader = LedgerDetailFixture(self.pg)
        old = self.reader.get(1)
        self.assertEqual(ledger_reader.get(1).model_dump(), old.model_dump())
        self.assertEqual(len(old.entities), 1)
        with self.pg() as c:
            from pipeline.store import _hash
            c.execute('UPDATE ingest_documents SET content_hash=%s WHERE id=1', (_hash('원문'),))
            same = store_document(c, source_type='blog', source_id='synthetic', title='제목',
                                  markdown='원문', media=['fixtures/new.jpg'])
            self.assertEqual(same['status'], 'unchanged')
        self.assertEqual(ledger_reader.get(1).images, ['fixtures/new.jpg'])
        self.assertEqual(ledger_reader.get(1).summary, '저장된 요약')
        self.assertEqual(len(ledger_reader.get(1).entities), 1)
        with self.pg() as c:
            changed = store_document(c, source_type='blog', source_id='synthetic', title='새 제목', markdown='새 본문')
            self.assertEqual(changed['status'], 'updated')
            new = store_document(c, source_type='note', source_id='new', title='새 노트', markdown='신규 원문')
        current = ledger_reader.get(1)
        self.assertEqual((current.title, current.content, current.summary, current.entities), ('새 제목', '새 본문', None, []))
        self.assertEqual(ledger_reader.get(new['id']).content, '신규 원문')
        self.assertEqual(self.reader.get(1).model_dump(), old.model_dump())

    def test_imported_video_job_keeps_transcript_after_new_digest(self):
        transcript = '합성 자막 ' * 30
        with self.fixture.connect() as c:
            c.execute("INSERT INTO raw_documents VALUES (10,'youtube','UCfixture/abc123def45','영상',"
                      "'https://example.test','2026-01-01',?,?,'failed',NULL,NULL)", (transcript,transcript))
            c.execute("INSERT INTO youtube_digest_jobs VALUES (10,?,'failed','old-token',1,'오류')", (transcript,))
            c.execute("INSERT INTO youtube_channels VALUES ('UCfixture','합성 채널',1)")
        self.load('2026-01-03T00:00:00+00:00')
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            state = c.execute('SELECT status,token FROM ingest_youtube_jobs WHERE document_id=10').fetchone()
            self.assertEqual(state, ('failed', None))
            job = queue_video(c, 10)
            self.assertTrue(finish_video(c, 10, revision=job['revision'], token=job['token'], digest='합성 정리본'))
        detail = LedgerDetailFixture(self.pg).get(10)
        self.assertEqual((detail.digest_status,detail.transcript,detail.summary), ('ok',transcript,None))
        self.assertIn('합성 정리본', detail.video_digest)
        self.assertEqual(self.reader.get(10).digest_status, 'failed')

    def test_ledger_to_separate_feed_generation_keeps_old_and_new_documents(self):
        transcript = '합성 영상 자막 ' * 20
        with self.fixture.connect() as c:
            c.execute("INSERT INTO raw_documents VALUES (10,'youtube','UCfixture/abc123def45','영상',"
                      "'https://example.test','2026-01-01',?,?,'pending',NULL,NULL)", (transcript,transcript))
        self.load('2026-01-03T00:00:00+00:00')
        old = self.reader.get(1)
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            store_document(c, source_type='note', source_id='synthetic-2', title='변경 문서', markdown='배터리 원문')
            new = store_document(c, source_type='note', source_id='new', title='신규 문서', markdown='신규 검색어')
            job = queue_video(c, 10)
            finish_video(c, 10, revision=job['revision'], token=job['token'], digest='합성 영상 정리본')
        destination = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn, options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as source:
            source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            snapshot = materialize(source)
            try:
                with patch('pipeline.visibility.feed_mute_sql', return_value=('1=1', [])):
                    load_snapshot(snapshot, target, snapshot_at='2026-01-04T00:00:00+00:00')
            finally:
                snapshot.close()
        reader = PostgreSQLDocumentReader(target)
        self.assertEqual(reader.list().total, 4)
        self.assertEqual(reader.get(1).model_dump(), old.model_dump())
        self.assertEqual(reader.get(2).content, '배터리 원문')
        self.assertEqual(reader.get(new['id']).content, '신규 검색어')
        self.assertEqual(reader.get(10).transcript, transcript)
        self.assertIn('합성 영상 정리본', reader.get(10).video_digest)
        self.assertEqual(self.reader.list().total, 3)
        with target() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            generation = c.execute('SELECT generation_id FROM snapshot_metadata').fetchone()[0]
            rows = c.execute("SELECT (row_data->>'id')::bigint,row_data->>'title',row_data->>'markdown' "
                             "FROM legacy_snapshot_rows WHERE table_name='raw_documents' ORDER BY row_ordinal").fetchall()
            index = SearchSnapshot(generation, rows)
            try:
                self.assertEqual(search_feed(c,index,'배터리').items[0].id, 2)
                self.assertEqual(search_feed(c,index,'신규').items[0].id, new['id'])
            finally:
                index.close()

    def test_projection_copy_keeps_existing_feed_and_vector_in_separate_schema(self):
        import struct
        self.load('2026-01-03T00:00:00+00:00')
        vector = struct.pack('<384f', 1.0, *([0.0] * 383))
        with self.pg() as c:
            generation = c.execute('SELECT generation_id FROM snapshot_metadata').fetchone()[0]
            c.execute('INSERT INTO document_embeddings VALUES (1,%s,%s)', (vector,'fixture'))
            c.execute("INSERT INTO document_embedding_metadata VALUES (TRUE,%s,'fixture',384,1,0,0)", (generation,))
            c.execute('INSERT INTO media_generations VALUES (%s)', (generation,))
            c.execute("INSERT INTO media_blobs VALUES ('fixture-digest',%s)", (b'fixture bytes',))
            c.execute("INSERT INTO media_generation_refs VALUES (%s,'fixture.jpg','fixture-digest')", (generation,))
        destination = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn, options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            result = copy_projection(c,self.schema,destination)
            self.assertEqual(result['tables'], len(PROJECTION_TABLES))
            self.assertNotEqual(result['generation'], generation)
        self.assertEqual(PostgreSQLDocumentReader(target).get(1).model_dump(), self.reader.get(1).model_dump())
        with target() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            self.assertEqual(c.execute('SELECT digest FROM media_generation_refs WHERE generation_id=%s',
                                       (result['generation'],)).fetchone()[0], 'fixture-digest')
            index = SearchSnapshot.from_postgres(c)
            try:
                self.assertEqual(search_feed(c,index,'없음',vector=vector).items[0].id, 1)
            finally:
                index.close()
        with self.assertRaisesRegex(ValueError, 'must be empty'):
            with self.pg() as c:
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                copy_projection(c,self.schema,destination)

    def test_note_overlay_preserves_existing_and_replaces_stale_search(self):
        import struct
        self.load('2026-01-03T00:00:00+00:00')
        old = self.reader.get(1)
        vector = struct.pack('<384f',1.0,*([0.0]*383))
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            generation = c.execute('SELECT generation_id FROM snapshot_metadata').fetchone()[0]
            c.execute('INSERT INTO document_embeddings VALUES (1,%s,%s),(2,%s,%s)', (vector,'a',vector,'b'))
            c.execute("INSERT INTO document_embedding_metadata VALUES (TRUE,%s,'fixture',384,2,0,0)", (generation,))
            c.execute("UPDATE legacy_snapshot_rows SET row_data=jsonb_set(row_data,'{content_hash}',to_jsonb('a'::text)) "
                      "WHERE table_name='raw_documents' AND row_data->>'id'='1'")
            store_document(c, source_type='note', source_id='synthetic-2', title='변경 자료', markdown='배터리 새 본문')
            new = store_document(c, source_type='note', source_id='new', title='신규 자료', markdown='새로운 내용')
        destination = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn, options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            self.assertEqual(copy_with_note_changes(c,self.schema,destination)['updated_documents'], 2)
        reader = PostgreSQLDocumentReader(target)
        self.assertEqual(reader.get(1).model_dump(), old.model_dump())
        self.assertEqual(reader.get(2).content, '배터리 새 본문')
        self.assertEqual(reader.list().total, 3)
        self.assertEqual(reader.list(source='note').total, 2)
        self.assertEqual(self.reader.list().total, 2)
        with target() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            self.assertEqual(c.execute('SELECT count(*) FROM document_embeddings').fetchone()[0], 1)
            index = SearchSnapshot.from_postgres(c)
            try:
                self.assertEqual(search_feed(c,index,'배터리').items[0].id,2)
                self.assertEqual(search_feed(c,index,'신규').items[0].id,new['id'])
            finally:
                index.close()

    def test_note_overlay_rejects_other_sources_without_partial_copy(self):
        self.load('2026-01-03T00:00:00+00:00')
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            store_document(c,source_type='memo',source_id='synthetic',title='changed',markdown='changed')
        destination = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn, options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.assertRaisesRegex(ValueError, 'Unsupported source change'):
            with self.pg() as c:
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                copy_with_note_changes(c,self.schema,destination)
        with target() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM document_projection').fetchone()[0],0)
        self.assertEqual(self.reader.list().total, 2)

    def test_blog_summary_update_preserves_filters_links_and_timeline(self):
        self.load('2026-01-03T00:00:00+00:00')
        before = self.reader.get(1)
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            job = claim_enrichment(c,document_id=1)
            finish_enrichment(c,document_id=1,**job,summary='새 블로그 요약',model='fixture')
            self.assertEqual(c.execute('SELECT count(*) FROM timeline_source_projection WHERE document_id=1').fetchone()[0],1)
        destination = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        reader = PostgreSQLDocumentReader(target)
        self.assertEqual(reader.get(1).summary,'새 블로그 요약')
        self.assertEqual(reader.get(1).entities,before.entities)
        self.assertEqual(reader.list(source='blog').items[0].summary,'새 블로그 요약')
        with target() as c:
            self.assertEqual(c.execute('SELECT document->>\'summary\' FROM timeline_source_projection WHERE document_id=1').fetchone()[0], '새 블로그 요약')
        self.assertEqual(self.reader.get(1).summary,before.summary)

    def test_youtube_summary_update_keeps_transcript_and_timeline(self):
        transcript='합성 자막 ' * 30
        with self.fixture.connect() as c:
            c.execute("INSERT INTO raw_documents VALUES (10,'youtube','UCfixture/abc123def45','영상',"
                      "'https://example.test','2026-01-01',?,?,'pending',NULL,NULL)",(transcript,transcript))
            c.execute("INSERT INTO youtube_channels VALUES ('UCfixture','합성 채널',1)")
        self.load('2026-01-03T00:00:00+00:00')
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            job=claim_enrichment(c,document_id=10)
            finish_enrichment(c,document_id=10,**job,summary='영상 요약',model='fixture')
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        reader=PostgreSQLDocumentReader(target)
        detail=reader.get(10)
        self.assertEqual((detail.summary,detail.transcript,detail.digest_status),('영상 요약',transcript,'pending'))
        self.assertEqual(reader.list(source='youtube').items[0].summary,'영상 요약')
        with target() as c:
            self.assertEqual(c.execute('SELECT document->>\'summary\' FROM timeline_source_projection WHERE document_id=10').fetchone()[0],'영상 요약')

    def test_existing_blog_content_change_updates_feed_and_timeline(self):
        self.load('2026-01-03T00:00:00+00:00')
        before=self.reader.get(1)
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            store_document(c,source_type='blog',source_id='synthetic',title='새 블로그 제목',
                           url='https://example.test/article',published_at='2026-01-01',
                           markdown='변경된 블로그 본문',raw_content='변경된 블로그 본문',media=['fixtures/example.jpg'])
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        reader=PostgreSQLDocumentReader(target)
        detail=reader.get(1)
        self.assertEqual((detail.title,detail.content,detail.summary,detail.entities),('새 블로그 제목','변경된 블로그 본문',None,[]))
        self.assertEqual(reader.list(source='blog').items[0].content,'변경된 블로그 본문')
        with target() as c:
            document=c.execute('SELECT document FROM timeline_source_projection WHERE document_id=1').fetchone()[0]
            self.assertEqual((document['content'],document['summary'],document['entities']),('변경된 블로그 본문',None,[]))
        self.assertEqual(self.reader.get(1).model_dump(),before.model_dump())

    def test_existing_youtube_digest_change_keeps_transcript_and_timeline(self):
        transcript='원본 자막 '*30
        with self.fixture.connect() as c:
            c.execute("INSERT INTO raw_documents VALUES (10,'youtube','UCfixture/abc123def45','영상',"
                      "'https://example.test','2026-01-01',?,?,'pending',NULL,NULL)",(transcript,transcript))
            c.execute("INSERT INTO youtube_channels VALUES ('UCfixture','합성 채널',1)")
        self.load('2026-01-03T00:00:00+00:00')
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            job=queue_video(c,10)
            finish_video(c,10,revision=job['revision'],token=job['token'],digest='영상 정리본')
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        reader=PostgreSQLDocumentReader(target)
        detail=reader.get(10)
        self.assertEqual((detail.transcript,detail.digest_status),(transcript,'ok'))
        self.assertIn('영상 정리본',detail.video_digest)
        self.assertIsNone(reader.list(source='youtube').items[0].transcript)
        with target() as c:
            document=c.execute('SELECT document FROM timeline_source_projection WHERE document_id=10').fetchone()[0]
            self.assertIn('영상 정리본',document['content'])
            self.assertIsNone(document['transcript'])
        self.assertEqual(self.reader.get(10).digest_status,'pending')

    def test_blog_url_change_reclassifies_feed_and_timeline(self):
        self.load('2026-01-03T00:00:00+00:00')
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            store_document(c,source_type='blog',source_id='synthetic',title='변경',url='https://other.test',
                           published_at='2026-01-01',markdown='변경',media=['fixtures/example.jpg'])
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        with target() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM timeline_source_projection WHERE document_id=1').fetchone()[0],0)
        reader=PostgreSQLDocumentReader(target)
        self.assertEqual(reader.get(1).url,'https://other.test')
        self.assertIsNone(reader.get(1).channel)
        self.assertEqual(reader.list(source='blog').total,0)
        self.assertEqual(self.reader.list().total,2)

    def test_blog_attachment_change_updates_timeline_and_preserves_summaries(self):
        import tempfile
        from pipeline.store import _hash
        self.load('2026-01-03T00:00:00+00:00')
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            c.execute('UPDATE ingest_documents SET content_hash=%s WHERE id=1',(_hash('원문'),))
            result=store_document(c,source_type='blog',source_id='synthetic',title='제목',markdown='원문',media=['new.png'])
            self.assertEqual(result['status'],'unchanged')
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'new.png').write_bytes(b'fixture image')
            with self.pg() as c:
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                result=copy_with_note_changes(c,self.schema,destination,media_root=tmp)
        reader=PostgreSQLDocumentReader(target)
        self.assertEqual(reader.get(1).images,['new.png'])
        self.assertEqual({item.summary for item in reader.list(source='blog').items},{'예전 요약','저장된 요약'})
        with target() as c:
            self.assertEqual(c.execute("SELECT document->'images' FROM timeline_source_projection WHERE document_id=1").fetchone()[0],['new.png'])
            blob=c.execute('SELECT b.content FROM media_generation_refs r JOIN media_blobs b ON b.digest=r.digest '
                           'WHERE r.generation_id=%s AND r.path=%s',(result['generation'],'new.png')).fetchone()
            self.assertEqual(bytes(blob[0]),b'fixture image')

    def test_blog_missing_publish_date_uses_preserved_fetch_time(self):
        with self.fixture.connect() as c:
            c.execute("UPDATE raw_documents SET fetched_at='2026-01-04T01:02:03Z' WHERE id=1")
        self.load('2026-01-03T00:00:00+00:00')
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            store_document(c,source_type='blog',source_id='synthetic',title='변경',
                           url='https://example.test/article',published_at='',fetched_at='2026-01-07T04:05:06Z',markdown='변경',
                           media=['fixtures/example.jpg'])
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        with target() as c:
            stamp,label=c.execute('SELECT occurred_at,time_label FROM timeline_source_projection WHERE document_id=1').fetchone()
            self.assertEqual((stamp.isoformat(),label),('2026-01-07T04:05:06+00:00','수집'))

    def test_new_blog_and_video_respect_registry_visibility_and_timeline(self):
        with self.fixture.connect() as c:
            c.execute("INSERT INTO youtube_channels VALUES ('UCfixture','영상 채널',1)")
            c.execute("INSERT INTO blog_sources VALUES ('https://muted.test/feed','rss','뮤트',0)")
        self.load('2026-01-03T00:00:00+00:00')
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            blog=store_document(c,source_type='blog',source_id='https://example.test/new',title='새 블로그',
                                url='https://example.test/new',published_at='2026-01-05',markdown='블로그 본문')
            fetched_blog=store_document(c,source_type='blog',source_id='https://example.test/no-date',title='수집시각 글',
                                        url='https://example.test/no-date',fetched_at='2026-01-04T01:02:03Z',markdown='본문')
            video=store_document(c,source_type='youtube',source_id='UCfixture/abc123def45',title='새 영상',
                                 url='https://youtube.com/watch?v=abc123def45',published_at='2026-01-05',
                                 markdown='영상 자막',raw_content='영상 자막',digest_status='pending')
            self.assertEqual(store_document(c,source_type='youtube',source_id='UCfixture/abc123def45',
                             title='새 영상',markdown='영상 자막')['status'],'unchanged')
            unregistered=store_document(c,source_type='youtube',source_id='notregistered',title='미등록 영상',
                                        markdown='미등록 자막',raw_content='미등록 자막',digest_status='pending')
            muted=store_document(c,source_type='blog',source_id='https://muted.test/post',title='뮤트 글',
                                 url='https://muted.test/post',published_at='2026-01-05',markdown='숨긴 본문')
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            self.assertEqual(copy_with_note_changes(c,self.schema,destination)['updated_documents'],5)
        reader=PostgreSQLDocumentReader(target)
        self.assertEqual(reader.list().total,6)
        self.assertIn(blog['id'],[item.id for item in reader.list(source='blog').items])
        self.assertIn(video['id'],[item.id for item in reader.list(source='youtube').items])
        self.assertNotIn(muted['id'],[item.id for item in reader.list().items])
        self.assertEqual(reader.get(video['id']).transcript,'영상 자막')
        with target() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            ids={r[0] for r in c.execute('SELECT document_id FROM timeline_source_projection')}
            self.assertTrue({blog['id'],video['id']}.issubset(ids))
            self.assertNotIn(muted['id'],ids)
            self.assertNotIn(unregistered['id'],ids)
            stamp,label=c.execute('SELECT occurred_at,time_label FROM timeline_source_projection WHERE document_id=%s',
                                  (fetched_blog['id'],)).fetchone()
            self.assertEqual((stamp.isoformat(),label),('2026-01-04T01:02:03+00:00','수집'))
            generation=c.execute('SELECT generation_id FROM snapshot_metadata').fetchone()[0]
            rows=c.execute("SELECT (row_data->>'id')::bigint,row_data->>'title',row_data->>'markdown' "
                           "FROM legacy_snapshot_rows WHERE table_name='raw_documents' ORDER BY row_ordinal").fetchall()
            index=SearchSnapshot(generation,rows)
            try:
                self.assertIn(blog['id'],[item.id for item in search_feed(c,index,'블로그').items])
                self.assertIn(video['id'],[item.id for item in search_feed(c,index,'자막').items])
                self.assertEqual(search_feed(c,index,'숨긴').total,0)
            finally:
                index.close()
        timeline=PostgreSQLTimelineSources(target)
        channels=timeline.channels(until='2026-01-06T00:00:00+00:00')
        self.assertIn('youtube:UCfixture',[channel.id for channel in channels.items])
        entries=timeline.timeline(channel='youtube:UCfixture',until='2026-01-06T00:00:00+00:00')
        self.assertEqual(entries.items[0].document.id,video['id'])
        self.assertEqual(self.reader.list().total,2)

    def test_note_overlay_updates_summary_without_discarding_matching_vector(self):
        import struct
        self.load('2026-01-03T00:00:00+00:00')
        vector = struct.pack('<384f',1.0,*([0.0]*383))
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            generation = c.execute('SELECT generation_id FROM snapshot_metadata').fetchone()[0]
            c.execute('INSERT INTO document_embeddings VALUES (2,%s,%s)', (vector,'fixture'))
            c.execute("INSERT INTO document_embedding_metadata VALUES (TRUE,%s,'fixture',384,1,0,0)", (generation,))
            job = claim_enrichment(c,document_id=2)
            finish_enrichment(c,document_id=2,**job,summary='새 요약',model='fixture')
        destination = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            self.assertEqual(copy_with_note_changes(c,self.schema,destination)['updated_documents'],1)
        target_reader = PostgreSQLDocumentReader(target)
        self.assertEqual(target_reader.get(2).summary, '새 요약')
        self.assertEqual(target_reader.list(source='note').items[0].summary, '새 요약')
        self.assertIsNone(self.reader.get(2).summary)
        with target() as c:
            self.assertEqual(bytes(c.execute('SELECT embedding FROM document_embeddings WHERE document_id=2').fetchone()[0]),vector)

    def test_overlay_accepts_only_current_matching_model_vector(self):
        import struct
        from pipeline.store import _hash
        self.load('2026-01-03T00:00:00+00:00')
        vector=struct.pack('<384f',1.0,*([0.0]*383))
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            generation=c.execute('SELECT generation_id FROM snapshot_metadata').fetchone()[0]
            c.execute("INSERT INTO document_embedding_metadata VALUES (TRUE,%s,'fixture-model',384,1,0,0)",(generation,))
            c.execute("INSERT INTO document_embeddings VALUES (1,%s,'base-hash')",(vector,))
            c.execute("UPDATE legacy_snapshot_rows SET row_data=jsonb_set(row_data,'{content_hash}',to_jsonb('base-hash'::text)) "
                      "WHERE table_name='raw_documents' AND row_data->>'id'='1'")
            c.execute('UPDATE ingest_documents SET content_hash=%s WHERE id=2',(_hash(''),))
            c.execute("UPDATE legacy_snapshot_rows SET row_data=jsonb_set(row_data,'{content_hash}',to_jsonb(%s::text)) "
                      "WHERE table_name='raw_documents' AND row_data->>'id'='2'",(_hash(''),))
            self.assertTrue(store_embedding(c,document_id=2,revision=1,embedding=vector,model='wrong-model'))
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.assertRaisesRegex(ValueError,'different model'):
            with self.pg() as c:
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                copy_with_note_changes(c,self.schema,destination)
        with target() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM document_projection').fetchone()[0],0)
        with self.pg() as c:
            self.assertFalse(store_embedding(c,document_id=2,revision=99,embedding=vector,model='fixture-model'))
            self.assertTrue(store_embedding(c,document_id=2,revision=1,embedding=vector,model='fixture-model'))
        with self.assertRaisesRegex(ValueError,'profile is not verified'):
            with self.pg() as c:
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                copy_with_note_changes(c,self.schema,destination)
        with self.pg() as c:
            c.execute("INSERT INTO embedding_profile_attestations VALUES (%s,'fixture:fixture-model')",(generation,))
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        with target() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            index=SearchSnapshot.from_postgres(c)
            try:
                self.assertIn(2,[item.id for item in search_feed(c,index,'없는단어',vector=vector).items])
            finally:
                index.close()

    @unittest.skipUnless(os.getenv('REFACTOR_LOCAL_EMBED_FIXTURE') == '1', 'local model cache not configured')
    def test_local_model_embedding_reaches_fixture_search(self):
        from pipeline.search import EMBED_MODEL
        self.load('2026-01-03T00:00:00+00:00')
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            generation=c.execute('SELECT generation_id FROM snapshot_metadata').fetchone()[0]
            c.execute('INSERT INTO document_embedding_metadata VALUES (TRUE,%s,%s,384,0,0,0)',(generation,EMBED_MODEL))
            new=store_document(c,source_type='note',source_id='model-fixture',title='합성 문서',markdown='테스트 문장')
        self.assertTrue(embed_document(self.pg,new['id']))
        with self.pg() as c:
            vector=bytes(c.execute('SELECT embedding FROM ingest_embeddings WHERE document_id=%s',(new['id'],)).fetchone()[0])
        destination='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_with_note_changes(c,self.schema,destination)
        with target() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            index=SearchSnapshot.from_postgres(c)
            try:
                self.assertEqual(search_feed(c,index,'없는단어',vector=vector).items[0].id,new['id'])
            finally:
                index.close()

    def test_note_media_change_keeps_all_existing_summaries_and_captures_bytes(self):
        import tempfile
        from pipeline.store import _hash
        with self.fixture.connect() as c:
            c.execute("INSERT INTO enrichments VALUES (3,2,'요약 하나','one','2026-01-01')")
            c.execute("INSERT INTO enrichments VALUES (4,2,'요약 둘','two','2026-01-02')")
        self.load('2026-01-03T00:00:00+00:00')
        with self.pg() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            c.execute('UPDATE ingest_documents SET content_hash=%s WHERE id=2', (_hash(''),))
            changed = store_document(c,source_type='note',source_id='synthetic-2',title='',markdown='',media=['new.png'])
            self.assertEqual(changed['status'], 'unchanged')
        destination = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(destination)))
        def cleanup():
            with psycopg.connect(self.dsn) as c:
                c.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(destination)))
        self.addCleanup(cleanup)
        def target(): return psycopg.connect(self.dsn,options=f'-c search_path={destination}')
        with target() as c:
            c.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/document_projection.sql').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                with self.pg() as c:
                    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                    copy_with_note_changes(c,self.schema,destination,media_root=tmp)
            with target() as c:
                self.assertEqual(c.execute('SELECT count(*) FROM document_projection').fetchone()[0],0)
            (Path(tmp)/'new.png').write_bytes(b'synthetic image bytes')
            with self.pg() as c:
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                result = copy_with_note_changes(c,self.schema,destination,media_root=tmp)
        reader = PostgreSQLDocumentReader(target)
        self.assertEqual(reader.get(2).images,['new.png'])
        self.assertEqual(reader.get(2).summary,'요약 둘')
        note = reader.list(source='note')
        self.assertEqual({item.summary for item in note.items},{'요약 하나','요약 둘'})
        self.assertEqual({item.content for item in note.items},{None})
        with target() as c:
            data = c.execute('SELECT b.content FROM media_generation_refs r JOIN media_blobs b ON b.digest=r.digest '
                             'WHERE r.generation_id=%s AND r.path=%s',(result['generation'],'new.png')).fetchone()
            self.assertEqual(bytes(data[0]),b'synthetic image bytes')

    def test_unsearched_feed_filters_preserve_sqlite_results(self):
        from routers import spine_feed
        self.load('2026-01-05T00:00:00+00:00')
        for filters in ({'days': 3650}, {'stock': '000000'},
                        {'source': 'blog', 'days': 3650, 'stock': '000000'}):
            with self.subTest(filters=filters), \
                    patch.object(spine_feed, 'get_connection', side_effect=self.fixture.connect), \
                    patch('pipeline.visibility.feed_mute_sql', return_value=('1=1', [])):
                expected = spine_feed.get_feed(q=None, source=filters.get('source'), stock=filters.get('stock'),
                                               industry=None, topic=None, page=1, size=20,
                                               days=filters.get('days'), sort='relevance')
                actual = self.reader.list(**filters)
            self.assertEqual(actual.total, expected.total)
            self.assertEqual([item.model_dump() for item in actual.items],
                             [item.model_dump() for item in expected.items])

    def test_replacement_idempotency_and_failure_rollback(self):
        first_at = '2026-01-03T00:00:00+00:00'
        second_at = '2026-01-04T00:00:00+00:00'
        result = self.load(first_at)
        self.assertEqual((result['documents'], result['list_rows']), (2, 3))
        self.assertEqual(self.reader.get(1).content, '원문')
        self.assertEqual(self.reader.list().total, 2)
        self.assertEqual(len(self.reader.list().items), 3)
        info = self.reader.snapshot_info()
        self.assertEqual(info['snapshot_at'], first_at)
        self.assertIsNotNone(info['source_observed_at'])
        self.assertGreaterEqual(info['loaded_at'], info['source_observed_at'])

        with closing(self.fixture.connect()) as c:
            c.execute("UPDATE raw_documents SET markdown='수정 원문',media_json='[\"fixtures/new.jpg\"]' WHERE id=1")
            c.execute('DELETE FROM raw_documents WHERE id=2')
            c.execute("INSERT INTO raw_documents VALUES(3,'note','n3','새 문서',NULL,'2026-01-05','새 원문',NULL,NULL,NULL,NULL)")
            c.commit()
        self.load(second_at)
        self.assertIsNone(self.reader.get(2))
        self.assertEqual(self.reader.get(1).images, ['fixtures/new.jpg'])
        self.assertEqual(self.reader.get(3).content, '새 원문')
        self.assertEqual(self.reader.snapshot_info()['snapshot_at'], second_at)
        with self.pg() as c:
            ids = {r[0] for r in c.execute("SELECT row_data->>'id' FROM legacy_snapshot_rows WHERE table_name='raw_documents'")}
            self.assertEqual(ids, {'1', '3'})
        before = [x.model_dump() for x in self.reader.list().items]
        self.load(second_at)
        self.assertEqual([x.model_dump() for x in self.reader.list().items], before)

        with self.pg() as c:
            c.execute("CREATE FUNCTION fail_fixture() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic failure'; END $$")
            c.execute('CREATE TRIGGER fail_fixture BEFORE INSERT ON document_projection FOR EACH ROW EXECUTE FUNCTION fail_fixture()')
        with self.assertRaises(psycopg.errors.RaiseException):
            self.load('2026-01-05T00:00:00+00:00')
        self.assertEqual([x.model_dump() for x in self.reader.list().items], before)
        self.assertEqual(self.reader.snapshot_info()['snapshot_at'], second_at)

    def test_combined_domain_failure_rolls_back_documents_and_sector(self):
        self.load('2026-01-03T00:00:00+00:00')
        before = self.reader.snapshot_info()
        with self.pg() as c:
            c.execute('CREATE TABLE combined_sector_fixture (generation UUID NOT NULL)')

        def sector_loader(source, target, *, peer_runtime, document_generation):
            target.execute('INSERT INTO combined_sector_fixture VALUES (%s)', (document_generation,))
            raise RuntimeError('sector load failed')

        source = sqlite3.connect(self.fixture.path.as_uri() + '?mode=ro', uri=True)
        source.row_factory = sqlite3.Row
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        try:
            with patch('pipeline.visibility.feed_mute_sql', return_value=('1=1', [])), \
                    patch('pipeline.postgres_sector_market.load_sector_market', side_effect=sector_loader):
                with self.assertRaisesRegex(RuntimeError, 'sector load failed'):
                    load_snapshot(source, self.pg, snapshot_at='2026-01-04T00:00:00+00:00',
                                  capacity_check=lambda *_: None, include_sector=True)
        finally:
            source.close()
        self.assertEqual(self.reader.snapshot_info(), before)
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM combined_sector_fixture').fetchone()[0], 0)


    def test_ties_visibility_source_filter_and_source_guard(self):
        with closing(self.fixture.connect()) as c:
            c.execute("UPDATE raw_documents SET published_at='2026-01-01' WHERE id=2")
            c.commit()
        source = sqlite3.connect(self.fixture.path.as_uri() + '?mode=ro', uri=True)
        source.row_factory = sqlite3.Row
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        try:
            with patch('pipeline.visibility.feed_mute_sql', return_value=('rd.id <> ?', [1])):
                result = load_snapshot(source, self.pg, snapshot_at='2026-01-06T00:00:00+00:00')
        finally:
            source.close()
        self.assertEqual((result['documents'], result['list_rows']), (2, 1))
        self.assertIsNotNone(self.reader.get(1))  # muted in feed, detail preserved
        self.assertEqual(self.reader.list().total, 1)
        self.assertEqual([x.id for x in self.reader.list(source='note').items], [2])
        self.assertEqual(self.reader.list(source='telegram').total, 0)
        self.assertEqual(self.reader.list(page=2, size=1).items, [])
        original = self.reader.snapshot_info()
        with closing(self.fixture.connect()) as unsafe:
            with self.assertRaises(ValueError):
                load_snapshot(unsafe, self.pg, snapshot_at='2026-01-07T00:00:00+00:00')
        self.assertEqual(self.reader.snapshot_info(), original)

    def test_pg_raw_rows_recreate_existing_detail_without_projection(self):
        from pipeline.document_read import _read_sqlite_document
        with closing(self.fixture.connect()) as c:
            c.execute("INSERT INTO entities VALUES(5,'company','다른 회사','000005')")
            c.execute("INSERT INTO entity_links VALUES(1,5,'stock',0.6)")
            c.execute("CREATE INDEX fixture_entity_order ON entity_links(doc_id,entity_id,link_type)")
            c.execute("INSERT INTO raw_documents VALUES(3,'youtube','yt/3','영상',NULL,'2026-01-03','정리본','자막','ok',NULL,NULL)")
            c.execute("INSERT INTO raw_documents VALUES(4,'youtube','yt/4','영상2',NULL,'2026-01-04',NULL,'원 자막','pending',NULL,NULL)")
            c.execute("INSERT INTO youtube_digest_jobs VALUES(4,'원 자막','failed','fixture',0,'합성 오류')")
            c.commit()
            expected = {i: _read_sqlite_document(c, i).model_dump() for i in (1, 2, 3, 4)}
        self.load('2026-01-05T00:00:00+00:00')
        with self.pg() as c:
            saved = c.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entity_digests'").fetchone()
            self.assertEqual(saved[0]['digest'], '합성 요약')
            saved = c.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='channel_reads'").fetchone()
            self.assertEqual(saved[0]['channel'], 'blog:fixture')
        raw_reader = PostgreSQLRawDocumentReader(self.pg)
        for doc_id, document in expected.items():
            self.assertEqual(raw_reader.get(doc_id).model_dump(), document)
        self.assertIsNone(raw_reader.get(999))
        # Raw reader must not depend on the cached response projection.
        with self.pg() as c:
            c.execute("UPDATE document_projection SET detail_document = jsonb_set(detail_document, '{content}', %s::jsonb) WHERE id=1", (json.dumps("projection only"),))
        self.assertEqual(raw_reader.get(1).model_dump(), expected[1])

    def test_source_timeline_filters_and_pagination_match_sqlite(self):
        from pipeline.timeline import timeline
        with closing(self.fixture.connect()) as c:
            c.execute("INSERT INTO raw_documents VALUES(3,'blog','b3','둘째','https://example.test/post','2026-01-01','내용',NULL,NULL,'[]',NULL)")
            c.commit()
            expected = {key: timeline(c, scope='sources', until='2026-01-02T00:00:00Z', **params)
                        for key, params in {'all': {}, 'blog': {'source': 'blog'},
                                            'channel': {'channel': 'blog:https://example.test/'},
                                            'empty': {'source': 'youtube'},
                                            'topic': {'topic': '합성 회사'},
                                            'page2': {'size': 1, 'page': 2}}.items()}
        self.load('2026-01-05T00:00:00+00:00')
        reader = PostgreSQLTimelineSources(self.pg)
        for key, params in {'all': {}, 'blog': {'source': 'blog'},
                            'channel': {'channel': 'blog:https://example.test/'},
                            'empty': {'source': 'youtube'}, 'topic': {'topic': '합성 회사'},
                            'page2': {'size': 1, 'page': 2}}.items():
            actual = reader.timeline(until='2026-01-02T00:00:00Z', **params)
            self.assertEqual([i.model_dump() for i in actual.items], [i.model_dump() for i in expected[key].items], key)
            self.assertEqual(actual.has_more, expected[key].has_more, key)

    def test_system_and_mixed_timeline_match_sqlite(self):
        from pipeline.timeline import timeline
        with closing(self.fixture.connect()) as c:
            c.execute("INSERT INTO source_digests VALUES (1,'person','합성 인물','저장 요약',1,'2026-01-01')")
            c.commit()
            cases = {'system': {'scope': 'system'}, 'person': {'scope': 'system', 'kind': 'person'},
                     'all': {'scope': 'all'}, 'topic': {'scope': 'all', 'topic': '합성 회사'}}
            expected = {key: timeline(c, until='2026-01-06T00:00:00Z', **params) for key, params in cases.items()}
        self.load('2026-01-06T00:00:00+00:00')
        reader = PostgreSQLTimelineSources(self.pg)
        for key, params in cases.items():
            actual = reader.timeline(until='2026-01-06T00:00:00Z', **params)
            self.assertEqual([i.model_dump() for i in actual.items], [i.model_dump() for i in expected[key].items], key)
            self.assertEqual(actual.has_more, expected[key].has_more, key)

    def test_rebuild_system_timeline_from_raw_and_rollback(self):
        with closing(self.fixture.connect()) as c:
            c.executescript("""
            INSERT INTO source_digests VALUES (1,'person','인물','요약',2,'2026-01-01');
            INSERT INTO transcript_follow VALUES ('MU','Micron',1);
            INSERT INTO transcripts VALUES (1,1,'MU',2025,'Q4','통화 요약','2026-01-01');
            INSERT INTO trade_follow VALUES ('1234','품목','그룹',1);
            INSERT INTO trade_stats VALUES ('1234','2025-12','2026-01-01');
            INSERT INTO narratives VALUES (1,'주제',1,'제목','본문',1,'2026-01-01');
            INSERT INTO reports VALUES (1,'주제','보고서','본문','[]','2026-01-01');
            INSERT INTO scenarios VALUES ('주제','답변',NULL,'2026-01-01');
            """)
            c.commit()
        self.load('2026-01-06T00:00:00+00:00')
        with self.pg() as c:
            expected = c.execute('SELECT * FROM timeline_system_projection ORDER BY id').fetchall()
            self.assertEqual(len(expected), 7)
            c.execute('DELETE FROM timeline_system_projection')
        self.assertEqual(rebuild_system_timeline(self.pg), len(expected))
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT * FROM timeline_system_projection ORDER BY id').fetchall(), expected)
            c.execute("CREATE FUNCTION fail_system() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic failure'; END $$")
            c.execute('CREATE TRIGGER fail_system BEFORE INSERT ON timeline_system_projection FOR EACH ROW EXECUTE FUNCTION fail_system()')
        with self.assertRaises(psycopg.errors.RaiseException):
            rebuild_system_timeline(self.pg)
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT * FROM timeline_system_projection ORDER BY id').fetchall(), expected)

    def test_inconsistent_enrichment_selection_fails_without_replacing_snapshot(self):
        from pipeline.timeline import _documents
        self.load('2026-01-05T00:00:00+00:00')
        before = self.reader.snapshot_info()
        def inconsistent(conn, ids):
            result = _documents(conn, ids)
            for doc in result.values():
                doc.summary = '다른 요약'
            return result
        with patch('pipeline.timeline._documents', side_effect=inconsistent):
            with self.assertRaisesRegex(ValueError, 'enrichment selection'):
                self.load('2026-01-06T00:00:00+00:00')
        self.assertEqual(self.reader.snapshot_info(), before)

    def test_rebuild_source_timeline_from_raw_and_failure_rolls_back(self):
        self.load('2026-01-06T00:00:00+00:00')
        with self.pg() as c:
            expected = c.execute('SELECT * FROM timeline_source_projection ORDER BY id').fetchall()
            self.assertTrue(expected)
            c.execute('DELETE FROM timeline_source_projection')
        self.assertEqual(rebuild_source_timeline(self.pg), len(expected))
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT * FROM timeline_source_projection ORDER BY id').fetchall(), expected)
            c.execute('DELETE FROM timeline_source_metadata WHERE document_id=%s', (expected[0][1],))
        with self.assertRaises(ValueError):
            rebuild_source_timeline(self.pg)
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT * FROM timeline_source_projection ORDER BY id').fetchall(), expected)

    def test_snapshot_replacement_does_not_repeat_prior_page(self):
        """A generation token keeps page two on the original immutable snapshot."""
        with closing(self.fixture.connect()) as c:
            c.execute("INSERT INTO raw_documents VALUES(3,'blog','b3','이전 글','https://example.test/old','2025-12-31','본문',NULL,NULL,'[]',NULL)")
            c.commit()
        self.load('2026-01-05T00:00:00+00:00')
        reader = PostgreSQLTimelineSources(self.pg)
        first = reader.timeline(scope='sources', size=1, page=1, until='2026-01-06T00:00:00Z')
        old_channels = reader.channels(until=first.until, include_owner_read_state=True).model_dump()
        details = PostgreSQLRawDocumentReader(self.pg)
        old_detail = details.get(1).model_dump()
        with closing(self.fixture.connect()) as c:
            c.execute("UPDATE raw_documents SET title='바뀐 제목' WHERE id=1")
            c.execute("UPDATE blog_sources SET blog_name='바뀐 출처'")
            c.execute("INSERT INTO raw_documents VALUES(4,'blog','b4','늦게 들어온 글','https://example.test/new','2026-01-02','본문',NULL,NULL,'[]',NULL)")
            c.commit()
        self.load('2026-01-07T00:00:00+00:00')
        second = reader.timeline(scope='sources', size=1, page=2, until=first.until, generation=first.generation)
        self.assertNotEqual(first.items[0].id, second.items[0].id)
        self.assertEqual(second.generation, first.generation)
        self.assertTrue(second.archived)
        self.assertTrue(details.get_with_generation_state(1, generation=first.generation)[1])
        self.assertFalse(details.get_with_generation_state(1)[1])
        from fastapi.testclient import TestClient
        script = Path(__file__).resolve().parents[2] / 'scripts/refactor_document_ui.py'
        spec = importlib.util.spec_from_file_location('refactor_archived_ui', script)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {'REFACTOR_FIXTURE_SCHEMA': self.schema}):
            spec.loader.exec_module(module)
        with TestClient(module.app) as client:
            old_doc = client.get('/api/spine/doc/1', params={'generation': first.generation})
            self.assertEqual(old_doc.status_code, 200)
            self.assertEqual(old_doc.headers['x-explorer-archived'], '1')
            old_feed = client.get('/api/spine/feed/timeline', params={'generation': first.generation})
            self.assertTrue(old_feed.json()['archived'])
        self.assertEqual(reader.channels(until=first.until, include_owner_read_state=True, generation=first.generation).model_dump(), old_channels)
        self.assertEqual(details.get(1, generation=first.generation).model_dump(), old_detail)
        self.assertNotEqual(details.get(1).title, old_detail['title'])
        self.assertIsNone(details.get(4, generation=first.generation))
        current = reader.timeline(scope='sources', size=1, page=2, until=first.until)
        self.assertEqual(current.items[0].id, first.items[0].id)  # compatibility path is unpinned
        with self.pg() as c:
            c.execute("UPDATE archived_timeline_generations SET expires_at=clock_timestamp()-interval '1 second' WHERE generation_id=%s", (first.generation,))
        with self.assertRaises(GenerationExpired):
            reader.timeline(scope='sources', size=1, page=2, until=first.until, generation=first.generation)
        with self.assertRaises(GenerationExpired):
            reader.channels(until=first.until, generation=first.generation)
        with self.assertRaises(GenerationExpired):
            details.get(1, generation=first.generation)

    def test_timeline_submillisecond_ties_and_until_match_sqlite(self):
        from pipeline.timeline import timeline
        with closing(self.fixture.connect()) as c:
            c.execute("INSERT INTO raw_documents VALUES(8,'telegram','t/8','A',NULL,'2026-01-01T00:00:00.000400Z','내용',NULL,NULL,'[]',NULL)")
            c.execute("INSERT INTO raw_documents VALUES(9,'telegram','t/9','B',NULL,'2026-01-01T00:00:00.000100Z','내용',NULL,NULL,'[]',NULL)")
            c.execute("INSERT INTO telegram_channels VALUES('t','채널',1)")
            c.execute("INSERT INTO channel_reads VALUES ('telegram:t','2026-01-01T00:00:00.000200Z',NULL)")
            c.commit()
            expected = [timeline(c, scope='sources', channel='telegram:t', size=1, page=page,
                                 until='2026-01-01T00:00:00.000200Z') for page in (1, 2)]
        self.load('2026-01-06T00:00:00+00:00')
        reader = PostgreSQLTimelineSources(self.pg)
        for page, wanted in enumerate(expected, 1):
            actual = reader.timeline(scope='sources', channel='telegram:t', size=1, page=page,
                                     until='2026-01-01T00:00:00.000200Z')
            self.assertEqual([i.id for i in actual.items], [i.id for i in wanted.items])
            self.assertEqual(actual.has_more, wanted.has_more)
        from pipeline.timeline import channels
        with closing(self.fixture.connect()) as c:
            expected_channels = channels(c, until='2026-01-01T00:00:00.000200Z')
        self.assertEqual(reader.channels(until='2026-01-01T00:00:00.000200Z', include_owner_read_state=True).model_dump(), expected_channels.model_dump())

    def test_old_generation_eviction_and_http_expiry(self):
        from fastapi.testclient import TestClient
        self.load('2026-01-01T00:00:00+00:00')
        reader = PostgreSQLTimelineSources(self.pg)
        first = reader.timeline(until='2026-01-09T00:00:00Z')
        self.load('2026-01-02T00:00:00+00:00')
        self.load('2026-01-03T00:00:00+00:00')
        self.load('2026-01-04T00:00:00+00:00')
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM archived_timeline_generations').fetchone()[0], 2)
        with self.assertRaises(GenerationExpired):
            reader.timeline(until=first.until, generation=first.generation)
        script = Path(__file__).resolve().parents[2] / 'scripts/refactor_document_ui.py'
        spec = importlib.util.spec_from_file_location('refactor_generation_ui', script)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {'REFACTOR_FIXTURE_SCHEMA': self.schema}):
            spec.loader.exec_module(module)
        with TestClient(module.app) as client:
            response = client.get('/api/spine/feed/timeline', params={'generation': first.generation})
            self.assertEqual(response.status_code, 410)
            self.assertEqual(client.get('/api/spine/feed/channels', params={'generation': first.generation}).status_code, 410)
            self.assertEqual(client.get('/api/spine/doc/1', params={'generation': first.generation}).status_code, 410)
            self.assertEqual(client.get('/api/spine/feed/timeline', params={'generation': 'bad'}).status_code, 422)
            response = client.get('/api/spine/feed/timeline')
            self.assertEqual(response.status_code, 200)
            active_generation = response.json()['generation']
            self.assertIsNotNone(uuid.UUID(active_generation))
            for path in ('/api/spine/feed/channels', '/api/spine/doc/1'):
                pinned = client.get(path, params={'generation': active_generation})
                self.assertEqual(pinned.status_code, 200)
                self.assertEqual(pinned.headers['x-explorer-generation'], active_generation)
                if path.startswith('/api/spine/doc/'):
                    self.assertEqual(pinned.headers['x-explorer-archived'], '0')

    def test_channel_directory_matches_sqlite_and_remains_readonly(self):
        from pipeline.timeline import channels
        with closing(self.fixture.connect()) as c:
            c.execute("INSERT INTO channel_reads VALUES ('*','2026-01-01T12:00:00Z',NULL)")
            c.commit()
            expected = channels(c, until='2026-01-06T00:00:00Z')
        self.load('2026-01-06T00:00:00+00:00')
        reader = PostgreSQLTimelineSources(self.pg)
        actual = reader.channels(until='2026-01-06T00:00:00Z', include_owner_read_state=True)
        self.assertEqual(actual.model_dump(), expected.model_dump())
        self.assertGreater(actual.total_unread, 0)
        with self.assertRaises(TypeError):
            reader.channels(until='2026-01-06T00:00:00Z', include_owner_read_state='false')
        anonymous = reader.channels(until='2026-01-06T00:00:00Z')
        self.assertEqual(anonymous.total_unread, 0)
        self.assertTrue(all(item.unread == 0 for item in anonymous.items))
        self.assertEqual([(i.id, i.count) for i in anonymous.items], [(i.id, i.count) for i in actual.items])
        self.assertEqual(reader.channels(until='2026-01-06T00:00:00Z', include_owner_read_state=True).model_dump(), expected.model_dump())

    def test_rebuild_details_from_pg_and_rollback_on_failure(self):
        self.load('2026-01-05T00:00:00+00:00')
        original = self.reader.get(1).model_dump()
        feed = [x.model_dump() for x in self.reader.list().items]
        with self.pg() as c:
            c.execute("UPDATE document_projection SET detail_document=jsonb_set(detail_document, '{content}', %s::jsonb) WHERE id=1", (json.dumps('stale'),))
        self.assertEqual(rebuild_details(self.pg), 2)
        self.assertEqual(self.reader.get(1).model_dump(), original)
        self.assertEqual([x.model_dump() for x in self.reader.list().items], feed)
        with self.pg() as c:
            c.execute("UPDATE document_projection SET detail_document=jsonb_set(detail_document, '{content}', %s::jsonb) WHERE id=1", (json.dumps('stale'),))
            c.execute("CREATE FUNCTION fail_rebuild() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.id=2 THEN RAISE EXCEPTION 'synthetic failure'; END IF; RETURN NEW; END $$")
            c.execute('CREATE TRIGGER fail_rebuild BEFORE UPDATE ON document_projection FOR EACH ROW EXECUTE FUNCTION fail_rebuild()')
        with self.assertRaises(psycopg.errors.RaiseException):
            rebuild_details(self.pg)
        self.assertEqual(self.reader.get(1).content, 'stale')

    def test_refuses_non_fixture_target_schema(self):
        source = sqlite3.connect(self.fixture.path.as_uri() + '?mode=ro', uri=True)
        source.row_factory = sqlite3.Row
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        try:
            factory = lambda: psycopg.connect(self.dsn, options='-c search_path=public')
            with self.assertRaises(ValueError):
                load_snapshot(source, factory, snapshot_at='2026-01-05T00:00:00+00:00')
        finally:
            source.close()

    def test_capacity_refusal_preserves_current_snapshot_and_archives(self):
        self.load('2026-01-05T00:00:00+00:00')
        before = self.reader.snapshot_info()
        with closing(self.fixture.connect()) as source:
            source.execute('PRAGMA query_only=ON')
            source.execute('BEGIN')
            with self.assertRaisesRegex(ValueError, 'capacity check'):
                load_snapshot(source, self.pg, snapshot_at='2026-01-06T00:00:00+00:00')
            with self.assertRaises(SnapshotCapacityError):
                load_snapshot(source, self.pg, snapshot_at='2026-01-06T00:00:00+00:00',
                    capacity_check=lambda src, dst: require_snapshot_capacity(src, dst,
                        host_probe=Path('/tmp'), vm_probe=Path('/tmp'), reserve_bytes=1 << 60))
            with self.assertRaises(SnapshotCapacityError):
                load_snapshot(source, self.pg, snapshot_at='2026-01-06T00:00:00+00:00',
                    capacity_check=lambda src, dst: require_snapshot_capacity(src, dst,
                        host_probe=Path('/not-a-probe'), vm_probe=Path('/tmp')))
            usage = namedtuple('usage', 'total used free')
            for free_values in ((1 << 50, 0), (0, 1 << 50)):
                with patch('pipeline.postgres_capacity.shutil.disk_usage', side_effect=[usage(1, 0, n) for n in free_values]):
                    with self.assertRaises(SnapshotCapacityError):
                        load_snapshot(source, self.pg, snapshot_at='2026-01-06T00:00:00+00:00',
                            capacity_check=lambda src, dst: require_snapshot_capacity(src, dst,
                                host_probe=Path('/tmp'), vm_probe=Path('/tmp')))
        self.assertEqual(self.reader.snapshot_info(), before)
        with self.pg() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM archived_timeline_generations').fetchone()[0], 0)
        self.assertEqual(self.reader.get(1).content, '원문')

    def test_older_snapshot_cannot_replace_newer(self):
        self.load('2026-01-05T00:00:00+00:00')
        with closing(self.fixture.connect()) as c:
            c.execute("UPDATE raw_documents SET markdown='older data' WHERE id=1")
            c.commit()
        with self.assertRaises(ValueError):
            self.load('2026-01-04T00:00:00+00:00')
        self.assertEqual(self.reader.get(1).content, '원문')
        self.assertEqual(self.reader.snapshot_info()['snapshot_at'], '2026-01-05T00:00:00+00:00')

    def test_concurrent_loader_waits_for_transaction_lock(self):
        blocker = self.pg()
        blocker.execute('SELECT pg_advisory_xact_lock(%s)', (SNAPSHOT_LOCK_KEY,))
        failures = []
        def run():
            try:
                self.load('2026-01-05T00:00:00+00:00')
            except Exception as exc:
                failures.append(exc)
        worker = threading.Thread(target=run)
        worker.start()
        try:
            deadline = time.monotonic() + 5
            waiting = False
            while time.monotonic() < deadline and worker.is_alive():
                with self.pg() as conn:
                    waiting = conn.execute(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' AND NOT granted)"
                    ).fetchone()[0]
                if waiting:
                    break
                time.sleep(0.02)
            self.assertTrue(waiting, 'loader must wait for the advisory transaction lock')
        finally:
            blocker.commit()
            blocker.close()
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertFalse(failures)
        self.assertEqual(self.reader.get(1).content, '원문')

    def test_unsupported_source_value_rolls_back_entire_snapshot(self):
        at = '2026-01-06T00:00:00+00:00'
        self.load(at)
        with closing(self.fixture.connect()) as c:
            c.execute('INSERT INTO youtube_digest_jobs VALUES(?,?,?,?,?,?)',
                      (1, 'synthetic', 'pending', sqlite3.Binary(b'\x00\x01'), 0, None))
            c.commit()
        with self.assertRaises(TypeError):
            self.load('2026-01-07T00:00:00+00:00')
        self.assertEqual(self.reader.get(1).content, '원문')
        self.assertEqual(self.reader.snapshot_info()['snapshot_at'], at)
        with self.pg() as c:
            count = c.execute("SELECT row_count FROM legacy_snapshot_tables WHERE table_name='youtube_digest_jobs'").fetchone()[0]
            self.assertEqual(count, 0)

    def test_source_filter_uses_existing_sqlite_tie_order_across_pages(self):
        from routers import spine_feed
        from tests.test_postgres_document_read import sqlite_feed
        with closing(self.fixture.connect()) as c:
            c.executescript("""
                INSERT INTO raw_documents VALUES
                  (3,'transcript','t3','컨콜3',NULL,'2026-01-05','본문3',NULL,NULL,NULL,NULL),
                  (4,'transcript','t4','컨콜4',NULL,'2026-01-05','본문4',NULL,NULL,NULL,NULL);
                CREATE INDEX fixture_source_order ON raw_documents(source_type, published_at DESC, id DESC);
                CREATE INDEX fixture_global_order ON raw_documents(published_at DESC, id ASC);
            """)
            c.commit()
        with patch.object(spine_feed, 'get_connection', side_effect=self.fixture.connect), \
             patch('pipeline.visibility.feed_mute_sql', return_value=('1=1', [])):
            expected = sqlite_feed(source='transcript', size=1, page=1)
            expected2 = sqlite_feed(source='transcript', size=1, page=2)
            global_order = [x.id for x in sqlite_feed().items if x.source_type == 'transcript']
        self.assertNotEqual(global_order, [expected.items[0].id, expected2.items[0].id])
        self.load('2026-01-06T00:00:00+00:00')
        actual = self.reader.list(source='transcript', size=1, page=1)
        actual2 = self.reader.list(source='transcript', size=1, page=2)
        self.assertEqual([x.model_dump() for x in actual.items], [x.model_dump() for x in expected.items])
        self.assertEqual([x.model_dump() for x in actual2.items], [x.model_dump() for x in expected2.items])

    def test_source_categories_and_original_rows_preserved(self):
        from routers import spine_feed
        from tests.test_postgres_document_read import sqlite_feed
        with closing(self.fixture.connect()) as c:
            c.executescript("""
                INSERT INTO blog_sources VALUES
                  ('https://example.test','naver','블로그',1),
                  ('https://rss.hankyung.com/feed','rss','뉴스',1),
                  ('https://rss.newsletter.test/feed','rss','기사',1);
                INSERT INTO raw_documents VALUES
                  (3,'blog','news-3','뉴스','https://www.hankyung.com/a','2026-01-04','뉴스 본문',NULL,NULL,NULL,NULL),
                  (4,'blog','article-4','기사','https://newsletter.test/a','2026-01-03','기사 본문',NULL,NULL,NULL,NULL);
                INSERT INTO entities VALUES (8,'person','합성 인물',NULL);
                INSERT INTO entity_links VALUES (4,8,'person',0.7);
                INSERT INTO follows VALUES (8);
            """)
            c.commit()
        with patch.object(spine_feed, 'get_connection', side_effect=self.fixture.connect), \
             patch('pipeline.visibility.feed_mute_sql', return_value=('1=1', [])):
            expected = {name: sqlite_feed(source=name) for name in ('blog','news','article','people')}
        self.load('2026-01-06T00:00:00+00:00')
        for name, wanted in expected.items():
            actual = self.reader.list(source=name)
            self.assertEqual(actual.total, wanted.total, name)
            self.assertEqual([x.model_dump() for x in actual.items],
                             [x.model_dump() for x in wanted.items], name)
        with self.pg() as c:
            raw = c.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' AND row_data->>'id'='3'").fetchone()[0]
            self.assertEqual((raw['source_type'], raw['source_id'], raw['markdown'], raw['raw_content']),
                             ('blog','news-3','뉴스 본문',None))
            saved = c.execute("SELECT count(*) FROM legacy_snapshot_rows WHERE table_name='enrichments'").fetchone()[0]
            self.assertEqual(saved, 2)
            columns = c.execute("SELECT columns FROM legacy_snapshot_tables WHERE table_name='raw_documents'").fetchone()[0]
            self.assertIn('media_json', columns)

    def test_tie_order_matches_sqlite_feed(self):
        from routers import spine_feed
        from tests.test_postgres_document_read import sqlite_feed
        with closing(self.fixture.connect()) as c:
            c.execute("UPDATE raw_documents SET published_at='2026-01-01' WHERE id=2")
            c.commit()
        with patch.object(spine_feed, 'get_connection', side_effect=self.fixture.connect), \
             patch('pipeline.visibility.feed_mute_sql', return_value=('1=1', [])):
            expected = sqlite_feed()
        self.load('2026-01-06T00:00:00+00:00')
        actual = self.reader.list()
        self.assertEqual([x.model_dump() for x in actual.items], [x.model_dump() for x in expected.items])
        pages = [self.reader.list(page=i, size=1).items for i in (1, 2, 3)]
        self.assertEqual([x.model_dump() for page in pages for x in page],
                         [x.model_dump() for x in expected.items])


if __name__ == '__main__':
    unittest.main()
