"""Disposable PostgreSQL ingest experiment; never connected to production.

The caller owns transaction boundaries. Slow summarization happens between
transactions. A revision, not only the hash, prevents stale A→B→A results.
"""
from hashlib import sha256
from uuid import uuid4
from psycopg.types.json import Jsonb


def store_document(conn, *, source_type, source_id, title, markdown, media=None,
                   url='', published_at='', raw_content='', digest_status=None):
    digest = sha256(markdown.encode('utf-8')).hexdigest()
    inserted = conn.execute(
        'INSERT INTO ingest_documents(source_type, source_id, title, markdown, content_hash, media_json, '
        'url, published_at, raw_content, digest_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) '
        'ON CONFLICT(source_type,source_id) DO NOTHING RETURNING id, revision',
        (source_type, source_id, title, markdown, digest, Jsonb(media) if media else None,
         url, published_at, raw_content, digest_status)).fetchone()
    if inserted:
        conn.execute("INSERT INTO ingest_enrichment_jobs(document_id,revision,status) VALUES (%s,%s,'pending')", inserted)
        return {'id': inserted[0], 'revision': inserted[1], 'status': 'new'}
    row = conn.execute(
        'SELECT id, revision, content_hash FROM ingest_documents '
        'WHERE source_type=%s AND source_id=%s FOR UPDATE', (source_type, source_id)).fetchone()
    if row[2] == digest:
        if media:
            conn.execute('UPDATE ingest_documents SET media_json=%s WHERE id=%s', (Jsonb(media), row[0]))
        return {'id': row[0], 'revision': row[1], 'status': 'unchanged'}
    revision = row[1] + 1
    conn.execute('UPDATE ingest_documents SET title=%s, markdown=%s, content_hash=%s, revision=%s, media_json=%s, '
                 'url=%s, published_at=%s, raw_content=%s, digest_status=%s WHERE id=%s',
                 (title, markdown, digest, revision, Jsonb(media) if media else None,
                  url, published_at, raw_content, digest_status, row[0]))
    conn.execute('DELETE FROM ingest_enrichments WHERE document_id=%s', (row[0],))
    conn.execute("UPDATE ingest_enrichment_jobs SET revision=%s,status='pending',token=NULL WHERE document_id=%s", (revision, row[0]))
    return {'id': row[0], 'revision': revision, 'status': 'updated'}


def claim_enrichment(conn, *, document_id, upgrade_keyword=False):
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
    conn.execute("UPDATE ingest_enrichment_jobs SET status='running',token=%s WHERE document_id=%s", (token, document_id))
    return {'revision': current[0], 'token': token}


def finish_enrichment(conn, *, document_id, revision, token, summary, model):
    current = conn.execute('SELECT revision FROM ingest_documents WHERE id=%s FOR UPDATE', (document_id,)).fetchone()
    job = conn.execute('SELECT revision,status,token FROM ingest_enrichment_jobs WHERE document_id=%s', (document_id,)).fetchone()
    if current is None or job is None or current[0] != revision or job != (revision, 'running', token):
        return False
    conn.execute('INSERT INTO ingest_enrichments(document_id, revision, summary, model) '
                 'VALUES (%s,%s,%s,%s) ON CONFLICT(document_id) DO UPDATE '
                 'SET revision=excluded.revision, summary=excluded.summary, model=excluded.model',
                 (document_id, revision, summary, model))
    conn.execute("UPDATE ingest_enrichment_jobs SET status='done',token=NULL WHERE document_id=%s", (document_id,))
    return True


def fail_enrichment(conn, *, document_id, revision, token):
    """Only the current claimant may release a failed/cancelled job for retry."""
    current = conn.execute('SELECT revision FROM ingest_documents WHERE id=%s FOR UPDATE', (document_id,)).fetchone()
    if current is None or current[0] != revision:
        return False
    return bool(conn.execute("UPDATE ingest_enrichment_jobs SET status='failed',token=NULL "
                             "WHERE document_id=%s AND revision=%s AND status='running' AND token=%s RETURNING 1",
                             (document_id, revision, token)).fetchone())
