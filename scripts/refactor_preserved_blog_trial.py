"""Disposable, offline BlogConnector trial with a preserved local snapshot.

Requires the isolated fixture database and a read-only source schema selected
by REFACTOR_FIXTURE_SCHEMA. No source text, URL, or document ID is printed.
The temporary write ledger and published schema are deleted on exit.
"""
import os
import re
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql
from pipeline.connectors.blog import BlogConnector
from pipeline.postgres_archive_import_fixture import import_archived_documents
from pipeline.postgres_graph_fixture import initialize_graph
from pipeline.postgres_ingest_cycle_fixture import run_exclusive_cycle
from pipeline.postgres_projection_copy_fixture import copy_projection
from pipeline.postgres_projection_publisher_fixture import FixturePublisher
from pipeline.postgres_document_read import PostgreSQLDocumentReader


def main():
    dsn = os.environ['REFACTOR_POSTGRES_DSN']
    source = os.environ['REFACTOR_FIXTURE_SCHEMA']
    params = psycopg.conninfo.conninfo_to_dict(dsn)
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or
        (params.get('host'), params.get('dbname'), params.get('user')) != ('pg','fixture','fixture') or
        not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', source)):
        raise ValueError('Disposable source fixture required')
    trial = 'refactor_fixture_' + uuid.uuid4().hex
    def factory():
        return psycopg.connect(dsn, options='-c search_path='+trial)
    def target(name):
        return psycopg.connect(dsn, options='-c search_path='+name)
    publisher = None
    created = False
    phase = 'prepare'
    exit_code = 0
    try:
        with psycopg.connect(dsn) as c:
            c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(trial)))
            created = True
        with factory() as c:
            c.execute((Path('/app/backend/refactor_sql/document_projection.sql')).read_text())
        with factory() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_projection(c, source, trial)
            c.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(trial)))
            c.execute(Path('/app/backend/refactor_sql/ingest_fixture.sql').read_text())
            count = import_archived_documents(c)
        # The graph importer explicitly requires read committed, while the
        # immutable projection copy above requires repeatable read.
        with factory() as c:
            initialize_graph(c)
            row = c.execute("SELECT id,title,url,published_at,raw_content FROM ingest_documents "
                "WHERE source_type='blog' AND source_id=url AND url<>'' AND length(raw_content)>=600 "
                "ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                raise ValueError('No suitable preserved blog input')
            previous_id, title, url, published, body = row
        print('archive documents imported:', count, flush=True)
        phase = 'collect'
        separator = '&' if '?' in url else '?'
        synthetic_url = url + separator + 'fixture=' + uuid.uuid4().hex
        token = 'refactorfixtureword'
        posts = [dict(title=title,url=url,published_at=published,content=body),
                 dict(title='fixture '+token,url=synthetic_url,published_at=published,
                      content=('<p>'+token+' 합성 본문</p>')*60)]
        connector = BlogConnector(['https://fixture.invalid/feed'])
        fake = lambda title,body: {'model':'fixture-fake','summary':'합성 요약'}
        with patch('pipeline.connectors.blog.detect_platform_and_feed_url',return_value=('fixture',None)), \
             patch('pipeline.connectors.blog.scrape_rss',return_value=(posts,'fixture')), \
             patch('services.blog_service.fetch_full_content',side_effect=AssertionError('network forbidden')), \
             patch('database.get_connection',side_effect=AssertionError('source SQLite forbidden')):
            first = run_exclusive_cycle(connector, factory, enrich=fake)
            second = run_exclusive_cycle(connector, factory, enrich=fake)
        if first['new'] != 1 or second['new'] or second['updated']:
            raise ValueError('Unexpected deduplication result')
        with factory() as c:
            new_id = c.execute("SELECT id FROM ingest_documents WHERE source_type='blog' AND source_id=%s",(synthetic_url,)).fetchone()[0]
            if c.execute('SELECT status FROM ingest_enrichment_jobs WHERE document_id=%s',(new_id,)).fetchone()[0] != 'done':
                raise ValueError('Synthetic enrichment incomplete')
        print('offline connector first: new', first['new'], 'updated', first['updated'],
              'second unchanged', second['unchanged'], 'enriched', first['enriched'], flush=True)
        phase = 'publish'
        publisher = FixturePublisher(factory, trial, target)
        publisher.publish()
        reader = PostgreSQLDocumentReader(lambda:target(publisher.active[0]))
        before = reader.get(previous_id)
        after = reader.get(new_id)
        found = publisher.search(token).items
        if before is None or after is None or after.summary != '합성 요약' or not any(item.id == new_id for item in found):
            raise ValueError('Published read or lexical search mismatch')
        print('published existing + new detail, fake summary and lexical search: PASS', flush=True)
    except BaseException as e:
        print('trial failed at',phase,'error type',type(e).__name__,flush=True)
        exit_code = 1
    finally:
        if publisher is not None:
            try:
                publisher.close()
            except Exception as e:
                print('published fixture cleanup failed:',type(e).__name__,flush=True)
                exit_code = 1
        if created:
            try:
                with psycopg.connect(dsn) as c:
                    c.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(trial)))
                print('temporary ledger removed',flush=True)
            except Exception as e:
                print('temporary ledger cleanup failed:',type(e).__name__,flush=True)
                exit_code = 1
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
