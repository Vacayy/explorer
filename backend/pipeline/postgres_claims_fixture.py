"""Document claims (D-233) for the single-path candidate: the legacy rules on a PG ledger.

The API keeps the legacy queue rules (reuse for the same body hash, short documents skipped,
running jobs left alone) and makes the one model call that extracts the claims, staging them
and queueing a `doc_claims` retrieval job. The compute worker runs `related_documents` for it:
the unchanged legacy `find_related` (chunk hybrid search + reranker) over the chunk index file,
with the projection attached, and publishes the result. A failure keeps its reason and is not retried
automatically; the screen's button queues it again.
"""
import json
import sqlite3
import time
import uuid

from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import _guard

TABLE = 'computed_doc_claims'


def initialize(conn):
    """Create the ledger and carry over the legacy doc_claims rows unchanged."""
    _guard(conn)
    with conn.transaction():
        if conn.execute(f"SELECT to_regclass('{TABLE}')").fetchone()[0] is not None:
            raise ValueError('Claims ledger already initialized')
        conn.execute(f'CREATE TABLE {TABLE} (doc_id BIGINT PRIMARY KEY,content_hash TEXT,status TEXT NOT NULL,token TEXT,'
                     'claims JSONB,payload JSONB,error TEXT,model TEXT,updated_at DOUBLE PRECISION)')
        rows = [row for (row,) in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='doc_claims'")]
        for row in rows:
            conn.execute(f'INSERT INTO {TABLE}(doc_id,content_hash,status,token,payload,error,model,updated_at) '
                         'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                         (row['doc_id'], row['content_hash'], row['status'], row['token'],
                          Jsonb(json.loads(row['payload'])) if row.get('payload') else None, row['error'], row['model'],
                          row['updated_at']))
        return len(rows)


def _document(conn, doc_id):
    row = conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' AND row_data->>'id'=%s",
                       (str(doc_id),)).fetchone()
    return row[0] if row else None


def queue(conn, doc_id):
    """{status, token} with the legacy rules; a token means the caller extracts in the background."""
    from pipeline.doc_claims import MIN_CHARS, MODEL, STALE_SECONDS
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('doc-claims',%s))", (doc_id,))
        doc = _document(conn, doc_id)
        if doc is None:
            return {'status': 'missing', 'token': None}
        row = conn.execute(f'SELECT status,content_hash,updated_at FROM {TABLE} WHERE doc_id=%s', (doc_id,)).fetchone()
        status, digest, updated = row if row else (None, None, None)
        if status in ('ok', 'skipped') and digest == doc.get('content_hash'):
            return {'status': status, 'token': None}
        if status in ('running', 'staged') and time.time() - (updated or 0) <= STALE_SECONDS:
            return {'status': 'running', 'token': None}
        short = len(doc.get('markdown') or doc.get('raw_content') or '') < MIN_CHARS
        token = None if short else uuid.uuid4().hex
        conn.execute(f'INSERT INTO {TABLE}(doc_id,content_hash,status,token,model,updated_at) VALUES (%s,%s,%s,%s,%s,%s) '
                     'ON CONFLICT (doc_id) DO UPDATE SET content_hash=excluded.content_hash,status=excluded.status,'
                     'token=excluded.token,claims=NULL,payload=NULL,error=NULL,model=excluded.model,updated_at=excluded.updated_at',
                     (doc_id, doc.get('content_hash'), 'skipped' if short else 'running', token, MODEL, time.time()))
        return {'status': 'skipped' if short else 'running', 'token': token}


def _finish(factory, doc_id, token, status, *, claims=None, payload=None, error=None):
    with factory() as conn:
        conn.execute(f'UPDATE {TABLE} SET status=%s,claims=COALESCE(%s,claims),payload=%s,error=%s,updated_at=%s '
                     'WHERE doc_id=%s AND token=%s',
                     (status, Jsonb(claims) if claims is not None else None, Jsonb(payload) if payload is not None else None,
                      error, time.time(), doc_id, token))


def extract(factory, doc_id, token, run_llm):
    """The legacy model step (one call): claims staged for the worker, or a kept failure."""
    from pipeline.doc_claims import INPUT_CHARS, PROMPT, _parse
    from pipeline.image_reading import strip_ai_notes
    try:
        with factory() as conn:
            doc = _document(conn, doc_id)
        body = strip_ai_notes(doc.get('markdown') or doc.get('raw_content') or '')[:INPUT_CHARS]
        claims = _parse(run_llm(PROMPT.format(title=doc.get('title') or '', body=body), task='document.claims').text)
        if not claims:
            raise ValueError('논점을 뽑지 못했습니다')
    except Exception as e:  # noqa: BLE001 - kept with its reason, as the legacy job does
        _finish(factory, doc_id, token, 'failed',
                error=f'논점을 정리하지 못했습니다({type(e).__name__}). Claude 인증·사용량을 확인한 뒤 다시 시도해 주세요.')
        return
    from pipeline.postgres_retrieval_jobs import enqueue
    with factory() as conn, conn.transaction():
        conn.execute(f"UPDATE {TABLE} SET status='staged',claims=%s,updated_at=%s WHERE doc_id=%s AND token=%s",
                     (Jsonb(claims), time.time(), doc_id, token))
        enqueue(conn, 'doc_claims', str(doc_id), {'doc_id': doc_id, 'token': token, 'claims': claims})


def state(conn, legacy, doc_id):
    """The legacy GET shape; `legacy` is a projection connection for related-document metadata."""
    from pipeline.doc_claims import STALE_SECONDS
    from pipeline.sources import source_names
    doc = _document(conn, doc_id)
    if doc is None:
        return None
    row = conn.execute(f'SELECT status,content_hash,payload,error,updated_at FROM {TABLE} WHERE doc_id=%s', (doc_id,)).fetchone()
    status, digest, payload, error, updated = row if row else (None, None, None, None, None)
    if status == 'staged':
        status = 'running'  # extracted, related documents still being found
    if status is None or (status in ('ok', 'skipped') and digest != doc.get('content_hash')):
        status = 'none'
    elif status == 'running' and time.time() - (updated or 0) > STALE_SECONDS:
        status = 'failed'
    claims = payload['claims'] if status == 'ok' and payload else []
    ids = [x['id'] for c in claims for x in c['related']]
    meta = {}
    if ids:
        rows = legacy.execute(f"SELECT id, source_type, source_id, url, title, published_at FROM raw_documents "
                              f"WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
        channels = source_names(legacy, rows)
        meta = {m['id']: {'source_type': m['source_type'], 'title': m['title'], 'published_at': m['published_at'],
                          'channel': (channels.get(m['id']) or {}).get('name')} for m in rows}
    claims = [{'claim': c['claim'], 'related': [{**x, **meta[x['id']]} for x in c['related'] if x['id'] in meta]}
              for c in claims]
    error = error if status == 'failed' else None
    if status == 'failed' and not error:
        error = '논점 정리가 중단되었습니다. 다시 시도해 주세요.'
    return {'status': status, 'error': error, 'claims': [c for c in claims if c['related']]}


def related_documents(factory, request):
    """Retrieval-job handler (compute worker): the claims' related documents, published to the ledger."""
    import database
    from pipeline import doc_claims
    from pipeline.doc_claims import RerankUnavailable, find_related
    doc_claims.get_connection = database.get_connection  # bound at import; `legacy_retrieval` set the target
    doc_id, token = request['doc_id'], request['token']
    try:
        payload = {'claims': find_related(doc_id, request['claims'])}
    except RerankUnavailable as e:
        _finish(factory, doc_id, token, 'failed',
                error=f'{e}. 관리자에게 검색 인덱스 작업(build_search_index) 상태를 확인해 달라고 해 주세요.')
        raise
    except Exception as e:
        _finish(factory, doc_id, token, 'failed', error=f'관련 자료를 찾지 못했습니다({type(e).__name__}). 다시 시도해 주세요.')
        raise
    _finish(factory, doc_id, token, 'ok', payload=payload)
    return {'claims': len(payload['claims'])}
