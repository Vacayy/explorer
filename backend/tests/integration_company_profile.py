"""Company web profile with the web research model and the DART fetch mocked (no external request).

Run only through `scripts/refactor_run_collector_once.sh backend/tests/integration_company_profile.py run|restore`.
This checks the candidate's publishing path (report row, source documents, ledgers), not the web research
itself, which needs the Claude CLI's web tools on this host.
"""
import json
import os
import socket
import sys

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

DSN, SCHEMA = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
PG_HOST = psycopg.conninfo.conninfo_to_dict(DSN)['host']
factory = lambda: psycopg.connect(DSN, options=f'-c search_path={SCHEMA}')
CODE = '005930'
SOURCE = f'POST /api/spine/company-profile/{CODE}'


def run():
    import database
    from pipeline import company_profile, llm
    from pipeline.llm import LLMResult
    from pipeline.postgres_legacy_projection import LegacyProjection
    from routers.postgres_legacy_read_fixture import _install_network_guard
    from routers.postgres_owner_records_fixture import create_router
    _install_network_guard(PG_HOST)
    real_resolve = socket.getaddrinfo
    socket.getaddrinfo = lambda host, *a, **k: real_resolve(host, *a, **k) if host == PG_HOST else (_ for _ in ()).throw(
        RuntimeError(f'external request blocked: {host}'))
    projection = LegacyProjection(factory, '/projection', external=True)
    database.get_connection = projection.connect
    company_profile.get_connection = projection.connect
    profile = {'overview': '합성 개요 RV11', 'business_lines': [{'name': '메모리', 'share_pct': 60, 'source_ids': [2]}],
               'sources': [{'id': 2, 'url': 'https://example.com/rv11-ir', 'title': '합성 IR', 'publisher': 'example',
                            'kind': 'ir', 'excerpt': '합성 발췌 RV11'}], 'gaps': []}
    llm.llm_engine = lambda: 'claude-code'
    llm.run = lambda prompt, *, task, system=None, **kw: LLMResult(
        text=json.dumps(profile, ensure_ascii=False), model='mock', engine='mock', cost_usd=0.0,
        tool_results=[{'name': 'WebFetch', 'input': {'url': 'https://example.com/rv11-ir'}}])
    import pipeline.dart_business as dart_business
    dart_business.ensure_business_text = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('DART mocked out'))
    app = FastAPI()
    app.include_router(create_router(factory, None, projection))
    response = TestClient(app).post(f'/api/spine/company-profile/{CODE}', json={'force': True})
    body = response.json()
    print('status', response.status_code, 'overview', body.get('profile', {}).get('overview'), 'reused', body.get('reused'),
          'sources', len(body.get('profile', {}).get('sources', [])), 'gaps', body.get('profile', {}).get('gaps'))
    with factory() as pg:
        print('ledger', pg.execute('SELECT table_name,count(*) FROM candidate_outputs WHERE source=%s GROUP BY 1', (SOURCE,)).fetchall(),
              'published docs', pg.execute('SELECT document_id FROM collected_publications').fetchall())


def restore():
    from pipeline.postgres_collected_documents_fixture import withdraw
    with factory() as pg:
        docs = [row[0] for row in pg.execute('SELECT document_id FROM collected_publications')]
        for doc in docs:
            withdraw(pg, doc)
        keys = pg.execute("SELECT table_name,row_key FROM candidate_outputs WHERE source=%s", (SOURCE,)).fetchall()
        removed = sum(pg.execute('DELETE FROM owner_row_overrides WHERE table_name=%s AND key=%s', key).rowcount for key in keys)
        outputs = pg.execute('DELETE FROM candidate_outputs WHERE source=%s', (SOURCE,)).rowcount
        vectors = pg.execute('DELETE FROM document_embedding_overrides WHERE document_id=ANY(%s)', (docs,)).rowcount
        pg.commit()
    print('withdrawn', docs, 'overrides', removed, 'outputs', outputs, 'vectors', vectors)


{'run': run, 'restore': restore}[sys.argv[1]]()
