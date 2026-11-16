"""Single-source, bounded external RSS read into a disposable PG fixture.

The selected URL comes from the captured registry. Only its public HTTPS RSS
is requested, once; full articles, models and operational databases are not
accessed. Collected text is never printed or written outside fixture schemas.
"""
import hashlib
import ipaddress
import os
import re
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

import feedparser
import psycopg
import requests
from psycopg import sql
from pipeline.connectors.blog import BlogConnector
from pipeline.postgres_archive_import_fixture import import_archived_documents
from pipeline.postgres_document_read import PostgreSQLDocumentReader
from pipeline.postgres_graph_fixture import initialize_graph
from pipeline.postgres_ingest_cycle_fixture import run_exclusive_cycle
from pipeline.postgres_projection_copy_fixture import copy_projection
from pipeline.postgres_projection_publisher_fixture import FixturePublisher
from services import blog_service


def main():
    dsn=os.environ['REFACTOR_POSTGRES_DSN']; source=os.environ['REFACTOR_FIXTURE_SCHEMA']
    params=psycopg.conninfo.conninfo_to_dict(dsn)
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or
        (params.get('host'),params.get('dbname'),params.get('user')) != ('pg','fixture','fixture') or
        not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',source)):
        raise ValueError('Disposable source required')
    trial='refactor_fixture_'+uuid.uuid4().hex
    def factory(): return psycopg.connect(dsn,options='-c search_path='+trial)
    def target(name): return psycopg.connect(dsn,options='-c search_path='+name)
    publisher=None; created=False; phase='prepare'; result=0
    try:
        with psycopg.connect(dsn) as c:
            c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(trial))); created=True
        with factory() as c:
            c.execute(Path('/app/backend/refactor_sql/document_projection.sql').read_text())
        with factory() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            copy_projection(c,source,trial)
            c.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(trial)))
            c.execute(Path('/app/backend/refactor_sql/ingest_fixture.sql').read_text())
            count=import_archived_documents(c)
        with factory() as c:
            initialize_graph(c)
            rows=c.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='blog_sources' ORDER BY row_ordinal").fetchall()
        candidates=[]
        for (row,) in rows:
            raw=row.get('url') or ''; u=urlsplit(raw)
            if (u.scheme=='https' and u.hostname and u.port in (None,443) and not u.username and not u.password and
                not u.query and not u.fragment and 'naver.com' not in u.hostname and
                row.get('collect_enabled') in (None,1) and row.get('is_active')==1 and
                (u.path.lower().endswith(('/rss','/feed','.xml','/atom')) or '/rss/' in u.path.lower())):
                candidates.append(raw)
        if not candidates: raise ValueError('No eligible registered RSS')
        feed=candidates[0]; host=urlsplit(feed).hostname
        addresses={entry[4][0] for entry in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
            raise ValueError('RSS hostname must resolve to public addresses')
        print('selected registered source host:',host,'source digest:',hashlib.sha256(feed.encode()).hexdigest()[:16],
              'UTC:',datetime.now(timezone.utc).isoformat(),flush=True)
        phase='external read'; calls=[]
        def bounded_feed(url):
            if url != feed or calls: raise ValueError('Unexpected extra external request')
            calls.append(1)
            with requests.Session() as session:
                session.trust_env=False
                with session.get(url,headers={'User-Agent':blog_service._UA},timeout=(5,12),
                                 allow_redirects=False,stream=True) as response:
                    response.raise_for_status()
                    if response.status_code != 200: raise ValueError('Unexpected RSS status')
                    chunks=[]; size=0
                    for chunk in response.iter_content(65536):
                        size+=len(chunk)
                        if size>2*1024*1024: raise ValueError('RSS exceeds limit')
                        chunks.append(chunk)
            return feedparser.parse(b''.join(chunks))
        original=blog_service.scrape_rss
        observed_urls=[]
        def limited_scrape(url):
            posts,name=original(url)
            selected=posts[:3]
            observed_urls.extend(p.get('url') or p.get('title','') for p in selected)
            return selected,name
        fake=lambda title,body:{'model':'fixture-fake','summary':'격리 시험 요약'}
        with patch('services.blog_service._parse_feed',side_effect=bounded_feed), \
             patch('pipeline.connectors.blog.scrape_rss',side_effect=limited_scrape), \
             patch('services.blog_service.fetch_full_content',return_value=None), \
             patch('database.get_connection',side_effect=AssertionError('operational SQLite forbidden')):
            connector=BlogConnector([feed]); stats=run_exclusive_cycle(connector,factory,enrich=fake)
        if len(calls)!=1 or not stats['docs']: raise ValueError('RSS returned no usable entries')
        print('RSS requests:',len(calls),'entries:',stats['docs'],'new:',stats['new'],
              'updated:',stats['updated'],'unchanged:',stats['unchanged'],'fake enrichments:',stats['enriched'],flush=True)
        phase='publish'
        publisher=FixturePublisher(factory,trial,target); publisher.publish()
        reader=PostgreSQLDocumentReader(lambda:target(publisher.active[0]))
        with factory() as c:
            seen=c.execute("SELECT id FROM ingest_documents WHERE source_type='blog' AND source_id=ANY(%s)",
                           (observed_urls,)).fetchall()
            changed=c.execute("SELECT id,title FROM ingest_documents WHERE source_type='blog' AND projection_version>projected_version ORDER BY id DESC LIMIT 1").fetchone()
        if len(seen)!=len(set(observed_urls)) or any(reader.get(row[0]) is None for row in seen):
            raise ValueError('Collected items missing from published reader')
        print('collected items visible in published reader:',len(seen),flush=True)
        if not changed:
            print('No changed document in selected feed; preserved archive remains available.',flush=True)
        else:
            doc=reader.get(changed[0])
            if doc is None: raise ValueError('Collected document missing from published reader')
            terms=re.findall(r'[A-Za-z]{4,}|[가-힣]{2,}',changed[1] or '')
            if terms:
                found=publisher.search(terms[0]).items
                print('collected detail visible; lexical search attempted:',True,
                      'result contains collected item:',any(x.id==changed[0] for x in found),flush=True)
            else: print('collected detail visible; lexical search unavailable for title',flush=True)
        print('archive documents:',count,'published projection: PASS',flush=True)
    except BaseException as e:
        print('trial failed at',phase,'error type',type(e).__name__,flush=True);result=1
    finally:
        if publisher is not None:
            try: publisher.close()
            except Exception as e: print('published fixture cleanup failed:',type(e).__name__,flush=True);result=1
        if created:
            try:
                with psycopg.connect(dsn) as c:c.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(trial)))
                print('temporary ledger removed',flush=True)
            except Exception as e:print('temporary ledger cleanup failed:',type(e).__name__,flush=True);result=1
    return result


if __name__=='__main__':raise SystemExit(main())
