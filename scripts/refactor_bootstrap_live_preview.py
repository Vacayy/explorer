"""Create a retained local-only fixture ledger with a clearly synthetic post.

No network or real model is used. The source is read but never modified.
On failure only schemas created by this invocation are dropped.
"""
import os
import re
import uuid
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql
from pipeline.connectors.blog import BlogConnector
from pipeline.postgres_archive_import_fixture import import_archived_documents
from pipeline.postgres_durable_publisher_fixture import DurableFixturePublisher
from pipeline.postgres_graph_fixture import initialize_graph
from pipeline.postgres_ingest_cycle_fixture import run_exclusive_cycle
from pipeline.postgres_projection_copy_fixture import copy_projection


def main():
    dsn=os.environ['REFACTOR_POSTGRES_DSN'];source=os.environ['REFACTOR_FIXTURE_SCHEMA']
    params=psycopg.conninfo.conninfo_to_dict(dsn)
    if (os.getenv('REFACTOR_TEST_DISPOSABLE')!='1' or
        (params.get('host'),params.get('dbname'),params.get('user'))!=('pg','fixture','fixture') or
        not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',source)):
        raise ValueError('Disposable source fixture required')
    ledger='refactor_fixture_'+uuid.uuid4().hex
    def factory():return psycopg.connect(dsn,options='-c search_path='+ledger)
    def target(name):return psycopg.connect(dsn,options='-c search_path='+name)
    publisher=None;created=False;success=False;phase='prepare'
    try:
        with psycopg.connect(dsn) as c:
            c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(ledger)));created=True
        with factory() as c:
            c.execute(Path('/app/backend/refactor_sql/document_projection.sql').read_text())
        with factory() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_projection(c,source,ledger)
            c.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(ledger)))
            c.execute(Path('/app/backend/refactor_sql/ingest_fixture.sql').read_text())
            count=import_archived_documents(c)
        with factory() as c:
            initialize_graph(c)
            rows=c.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='blog_sources' ORDER BY row_ordinal").fetchall()
        urls=[r[0].get('url') for r in rows if r[0].get('is_active')==1 and isinstance(r[0].get('url'),str)
              and r[0]['url'].startswith('https://') and 'blog.naver.com' not in r[0]['url']
              and not any(ch in r[0]['url'] for ch in ('?','#'))]
        if not urls:raise ValueError('Active blog registry required')
        token='syntheticfixture'+uuid.uuid4().hex[:10]
        url=urls[0].rstrip('/')+'/__local_fixture_'+token
        post={'title':'[합성 수집 시험] '+token,'url':url,'published_at':datetime.now(timezone.utc).isoformat(),
              'content':('<p>실제 투자 자료가 아닌 합성 시험 본문 '+token+'</p>')*30}
        connector=BlogConnector([urls[0]])
        fake=lambda title,body:{'summary':'합성 시험 요약: 실제 투자 데이터가 아닙니다. '+token,'model':'fixture-fake'}
        phase='collect'
        with patch('pipeline.connectors.blog.detect_platform_and_feed_url',return_value=('fixture',None)), \
             patch('pipeline.connectors.blog.scrape_rss',return_value=([post],'fixture')), \
             patch('services.blog_service.fetch_full_content',side_effect=AssertionError('network forbidden')), \
             patch('database.get_connection',side_effect=AssertionError('operational SQLite forbidden')):
            stats=run_exclusive_cycle(connector,factory,enrich=fake)
        if stats['new']!=1 or stats['enriched']!=1:raise ValueError('Synthetic collection failed')
        with factory() as c:
            doc_id=c.execute("SELECT id FROM ingest_documents WHERE source_type='blog' AND source_id=%s",(url,)).fetchone()[0]
        phase='publish'
        publisher=DurableFixturePublisher(factory,ledger,target);publisher.initialize();generation=publisher.publish()
        detail=publisher.get(doc_id)
        if detail is None or not detail.summary or not any(x.id==doc_id for x in publisher.search(token).items):
            raise ValueError('Published document unavailable')
        publisher.close();publisher=None
        success=True
        print('READY ledger',ledger,'generation',generation,'document',doc_id,'token',token,'baseline documents',count,flush=True)
    except BaseException as e:
        print('bootstrap failed at',phase,'error type',type(e).__name__,flush=True)
    finally:
        if publisher is not None:publisher.close()
        if created and not success:
            with factory() as c:
                exists=c.execute("SELECT to_regclass('fixture_publication_stages') IS NOT NULL").fetchone()[0]
                stages=[r[0] for r in c.execute('SELECT schema_name FROM fixture_publication_stages')] if exists else []
            with psycopg.connect(dsn) as c:
                for name in stages:
                    if not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',name) or name in (source,ledger):
                        raise ValueError('Unexpected cleanup schema')
                    c.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(name)))
                c.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(ledger)))
            print('failed bootstrap schemas removed',flush=True)
    return 0 if success else 1


if __name__=='__main__':raise SystemExit(main())
