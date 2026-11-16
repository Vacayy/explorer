"""Temporary synthetic collection + PG projection for a local browser trial."""
import signal
import threading
import uuid
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

from tests.test_postgres_snapshot import SnapshotReplacementTests
from pipeline.connectors.blog import BlogConnector
from pipeline.postgres_archive_import_fixture import import_archived_documents
from pipeline.postgres_graph_fixture import initialize_graph
from pipeline.postgres_ingest_cycle_fixture import run_exclusive_cycle
from pipeline.postgres_projection_publisher_fixture import FixturePublisher
import psycopg


def main():
    fixture=SnapshotReplacementTests('test_registered_sources_through_existing_enrichment')
    publisher=None
    fixture.setUp()
    try:
        with fixture.fixture.connect() as c:
            c.execute('CREATE TABLE entity_keywords(entity_id INTEGER,keyword TEXT,status TEXT)')
            c.execute('CREATE TABLE entity_relations(src_id INTEGER,dst_id INTEGER,rel_type TEXT,epistemic_type TEXT,confidence REAL,source_doc_id INTEGER,valid_from TEXT)')
        fixture.load('2026-01-03T00:00:00+00:00',include_linking=True)
        with fixture.pg() as c:
            c.execute(Path('/app/backend/refactor_sql/ingest_fixture.sql').read_text())
            import_archived_documents(c)
            initialize_graph(c)
        token='syntheticnewspaper'+uuid.uuid4().hex[:8]
        url='https://example.test/'+token
        post={'title':'합성 수집 문서 '+token,'url':url,'published_at':datetime.now(timezone.utc).isoformat(),
              'content':('<p>'+token+' 합성 수집 본문</p>')*60}
        connector=BlogConnector(['https://example.test/'])
        fake=lambda title,body:{'summary':'합성 수집 요약 '+token,'model':'fixture-fake'}
        with patch('pipeline.connectors.blog.detect_platform_and_feed_url',return_value=('fixture',None)), \
             patch('pipeline.connectors.blog.scrape_rss',return_value=([post],'합성 채널')), \
             patch('services.blog_service.fetch_full_content',side_effect=AssertionError('network forbidden')), \
             patch('database.get_connection',side_effect=AssertionError('operating DB forbidden')):
            result=run_exclusive_cycle(connector,fixture.pg,enrich=fake)
        if result['new'] != 1 or result['enriched'] != 1:
            raise ValueError('Synthetic collection failed')
        with fixture.pg() as c:
            doc_id=c.execute("SELECT id FROM ingest_documents WHERE source_type='blog' AND source_id=%s",(url,)).fetchone()[0]
        def target(schema):return psycopg.connect(fixture.dsn,options='-c search_path='+schema)
        publisher=FixturePublisher(fixture.pg,fixture.schema,target)
        generation=publisher.publish()
        if not any(item.id==doc_id for item in publisher.search(token).items):
            raise ValueError('Synthetic search failed')
        print('READY',publisher.active[0],doc_id,token,str(generation),flush=True)
        stop=threading.Event()
        signal.signal(signal.SIGTERM,lambda *_:stop.set())
        signal.signal(signal.SIGINT,lambda *_:stop.set())
        stop.wait()
    finally:
        if publisher is not None:
            publisher.close()
        fixture.tearDown()
        print('synthetic UI fixture cleaned',flush=True)


if __name__=='__main__':main()
