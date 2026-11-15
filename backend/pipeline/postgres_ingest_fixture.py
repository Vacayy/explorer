"""Disposable PostgreSQL ingest experiment; never connected to production.

The caller owns transaction boundaries. Slow summarization happens between
transactions. A revision, not only the hash, prevents stale A→B→A results.
"""
from hashlib import sha256
import math
import struct
from uuid import uuid4
from psycopg.types.json import Jsonb
from pipeline.dates import to_iso_utc
from pipeline.normalize import to_markdown


def store_document(conn, *, source_type, source_id, title, markdown, media=None,
                   url='', published_at='', fetched_at=None, raw_content='', digest_status=None):
    digest = sha256(markdown.encode('utf-8')).hexdigest()
    inserted = conn.execute(
        'INSERT INTO ingest_documents(source_type, source_id, title, markdown, content_hash, media_json, '
        'url, published_at, raw_content, digest_status, fetched_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) '
        'ON CONFLICT(source_type,source_id) DO NOTHING RETURNING id, revision',
        (source_type, source_id, title, markdown, digest, Jsonb(media) if media else None,
         url, published_at, raw_content, digest_status, fetched_at)).fetchone()
    if inserted:
        conn.execute("INSERT INTO ingest_enrichment_jobs(document_id,revision,status) VALUES (%s,%s,'pending')", inserted)
        return {'id': inserted[0], 'revision': inserted[1], 'status': 'new'}
    row = conn.execute(
        'SELECT id, revision, content_hash FROM ingest_documents '
        'WHERE source_type=%s AND source_id=%s FOR UPDATE', (source_type, source_id)).fetchone()
    if row[2] == digest:
        if media:
            conn.execute('UPDATE ingest_documents SET media_json=%s, projection_version=projection_version+1 '
                         'WHERE id=%s AND media_json IS DISTINCT FROM %s', (Jsonb(media), row[0], Jsonb(media)))
        return {'id': row[0], 'revision': row[1], 'status': 'unchanged'}
    revision = row[1] + 1
    conn.execute('UPDATE ingest_documents SET title=%s, markdown=%s, content_hash=%s, revision=%s, media_json=%s, '
                 'url=%s, published_at=%s, raw_content=%s, digest_status=%s, fetched_at=%s, '
                 'projection_version=projection_version+1,enrichment_dirty=FALSE,embedding_dirty=FALSE,links_dirty=FALSE WHERE id=%s',
                 (title, markdown, digest, revision, Jsonb(media) if media else None,
                  url, published_at, raw_content, digest_status, fetched_at, row[0]))
    conn.execute('INSERT INTO ingest_enrichment_history(document_id,revision,summary,model,sentiment,time_orientation,reference_period) '
                 'SELECT document_id,revision,summary,model,sentiment,time_orientation,reference_period FROM ingest_enrichments WHERE document_id=%s '
                 'ON CONFLICT(document_id,revision) DO NOTHING', (row[0],))
    conn.execute('DELETE FROM ingest_enrichments WHERE document_id=%s', (row[0],))
    conn.execute('DELETE FROM ingest_embeddings WHERE document_id=%s', (row[0],))
    conn.execute('DELETE FROM ingest_entity_links WHERE document_id=%s', (row[0],))
    conn.execute("UPDATE ingest_enrichment_jobs SET revision=%s,status='pending',token=NULL,worker_id=NULL,started_at=NULL WHERE document_id=%s", (revision, row[0]))
    return {'id': row[0], 'revision': revision, 'status': 'updated'}


def store_raw_doc(conn, doc, *, fetched_at=None):
    """Fixture adapter for the existing connector's RawDoc contract."""
    return store_document(conn, source_type=doc.source_type, source_id=doc.source_id,
                          title=doc.title, markdown=to_markdown(doc), media=doc.images,
                          url=doc.url, published_at=to_iso_utc(doc.published_at) or '',
                          raw_content=doc.raw_content, digest_status=doc.digest_status, fetched_at=fetched_at)


def store_embedding(conn, *, document_id, revision, embedding, model='synthetic-fixture'):
    """Accept a precomputed fixture vector only for the current source revision."""
    if (not isinstance(embedding, bytes) or len(embedding) != 1536 or
            not all(math.isfinite(v[0]) for v in struct.iter_unpack('<f', embedding))):
        raise ValueError('Expected 384 finite float32 values')
    row = conn.execute('SELECT revision,content_hash FROM ingest_documents WHERE id=%s FOR UPDATE', (document_id,)).fetchone()
    if row is None or row[0] != revision:
        return False
    if not model:
        raise ValueError('Embedding model is required')
    conn.execute('INSERT INTO ingest_embeddings VALUES (%s,%s,%s,%s) '
                 'ON CONFLICT(document_id) DO UPDATE SET revision=excluded.revision,embedding=excluded.embedding,model=excluded.model',
                 (document_id, revision, embedding, model))
    conn.execute('UPDATE ingest_documents SET projection_version=projection_version+1,embedding_dirty=TRUE WHERE id=%s', (document_id,))
    return True


def claim_enrichment(conn, *, document_id, worker_id='fixture-worker', upgrade_keyword=False):
    """Claim once per document/revision; caller commits before invoking model."""
    current = conn.execute('SELECT revision FROM ingest_documents WHERE id=%s FOR UPDATE', (document_id,)).fetchone()
    if current is None:
        return None
    job = conn.execute('SELECT status FROM ingest_enrichment_jobs WHERE document_id=%s', (document_id,)).fetchone()
    if job[0] == 'done' and upgrade_keyword:
        cached = conn.execute('SELECT model FROM ingest_enrichments WHERE document_id=%s', (document_id,)).fetchone()
        if not cached or cached[0] != 'keyword':
            return None
    elif job[0] not in ('pending', 'failed'):
        return None
    token = uuid4()
    if not worker_id:
        raise ValueError('worker_id is required')
    conn.execute("UPDATE ingest_enrichment_jobs SET status='running',token=%s,worker_id=%s,started_at=clock_timestamp() WHERE document_id=%s", (token, worker_id, document_id))
    return {'revision': current[0], 'token': token}


def finish_enrichment(conn, *, document_id, revision, token, summary, model, sentiment=None, time_orientation=None, reference_period=None):
    current = conn.execute('SELECT revision FROM ingest_documents WHERE id=%s FOR UPDATE', (document_id,)).fetchone()
    job = conn.execute('SELECT revision,status,token FROM ingest_enrichment_jobs WHERE document_id=%s', (document_id,)).fetchone()
    if current is None or job is None or current[0] != revision or job != (revision, 'running', token):
        return False
    conn.execute('INSERT INTO ingest_enrichments(document_id,revision,summary,model,sentiment,time_orientation,reference_period) '
                 'VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(document_id) DO UPDATE '
                 'SET revision=excluded.revision,summary=excluded.summary,model=excluded.model,sentiment=excluded.sentiment, '
                 'time_orientation=excluded.time_orientation,reference_period=excluded.reference_period',
                 (document_id,revision,summary,model,sentiment,time_orientation,reference_period))
    conn.execute('UPDATE ingest_documents SET projection_version=projection_version+1,enrichment_dirty=TRUE WHERE id=%s', (document_id,))
    conn.execute("UPDATE ingest_enrichment_jobs SET status='done',token=NULL,worker_id=NULL,started_at=NULL WHERE document_id=%s", (document_id,))
    return True


def fail_enrichment(conn, *, document_id, revision, token):
    """Only the current claimant may release a failed/cancelled job for retry."""
    current = conn.execute('SELECT revision FROM ingest_documents WHERE id=%s FOR UPDATE', (document_id,)).fetchone()
    if current is None or current[0] != revision:
        return False
    return bool(conn.execute("UPDATE ingest_enrichment_jobs SET status='failed',token=NULL,worker_id=NULL,started_at=NULL "
                             "WHERE document_id=%s AND revision=%s AND status='running' AND token=%s RETURNING 1",
                             (document_id, revision, token)).fetchone())


def publish_projection(conn, *, document_id, version, publish):
    """Publish atomically; caller provides the actual projection writer in this transaction."""
    row = conn.execute('SELECT projection_version,projected_version FROM ingest_documents WHERE id=%s FOR UPDATE',
                       (document_id,)).fetchone()
    if row is None or row[0] != version or row[1] == version:
        return False
    publish(conn, document_id)
    conn.execute('UPDATE ingest_documents SET projected_version=%s WHERE id=%s', (version, document_id))
    return True
