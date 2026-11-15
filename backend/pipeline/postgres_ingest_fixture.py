"""Disposable PostgreSQL ingest experiment; never connected to production.

The caller owns transaction boundaries. Slow summarization happens between
transactions. A revision, not only the hash, prevents stale A→B→A results.
"""
from hashlib import sha256
from psycopg.types.json import Jsonb


def store_document(conn, *, source_type, source_id, title, markdown, media=None):
    digest = sha256(markdown.encode('utf-8')).hexdigest()
    inserted = conn.execute(
        'INSERT INTO ingest_documents(source_type, source_id, title, markdown, content_hash, media_json) '
        'VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(source_type,source_id) DO NOTHING '
        'RETURNING id, revision', (source_type, source_id, title, markdown, digest, Jsonb(media) if media else None)).fetchone()
    if inserted:
        return {'id': inserted[0], 'revision': inserted[1], 'status': 'new'}
    row = conn.execute(
        'SELECT id, revision, content_hash FROM ingest_documents '
        'WHERE source_type=%s AND source_id=%s FOR UPDATE', (source_type, source_id)).fetchone()
    if row[2] == digest:
        if media:
            conn.execute('UPDATE ingest_documents SET media_json=%s WHERE id=%s', (Jsonb(media), row[0]))
        return {'id': row[0], 'revision': row[1], 'status': 'unchanged'}
    revision = row[1] + 1
    conn.execute('UPDATE ingest_documents SET title=%s, markdown=%s, content_hash=%s, revision=%s, media_json=%s WHERE id=%s',
                 (title, markdown, digest, revision, Jsonb(media) if media else None, row[0]))
    conn.execute('DELETE FROM ingest_enrichments WHERE document_id=%s', (row[0],))
    return {'id': row[0], 'revision': revision, 'status': 'updated'}


def apply_enrichment(conn, *, document_id, revision, summary, model):
    current = conn.execute('SELECT revision FROM ingest_documents WHERE id=%s FOR UPDATE',
                           (document_id,)).fetchone()
    if current is None or current[0] != revision:
        return False
    conn.execute('INSERT INTO ingest_enrichments(document_id, revision, summary, model) '
                 'VALUES (%s,%s,%s,%s) ON CONFLICT(document_id) DO UPDATE '
                 'SET revision=excluded.revision, summary=excluded.summary, model=excluded.model',
                 (document_id, revision, summary, model))
    return True
