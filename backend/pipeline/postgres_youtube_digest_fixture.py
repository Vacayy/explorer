"""Explicit synthetic video digest admission/completion; no model calls."""
import time
from uuid import uuid4
from pipeline.connectors.youtube import _digest_body
from pipeline.postgres_ingest_fixture import store_document


def queue(conn, document_id):
    doc = conn.execute('SELECT source_type,revision,raw_content,digest_status FROM ingest_documents WHERE id=%s FOR UPDATE', (document_id,)).fetchone()
    if not doc or doc[0] != 'youtube':
        raise ValueError('video not found')
    if doc[3] == 'ok':
        return None
    job = conn.execute('SELECT revision,transcript,status FROM ingest_youtube_jobs WHERE document_id=%s', (document_id,)).fetchone()
    if job and job[0] == doc[1] and job[2] == 'generating':
        return None
    transcript = job[1] if job and job[0] == doc[1] else doc[2]
    if len(transcript) < 100:
        raise ValueError('transcript too short')
    token = uuid4()
    conn.execute("INSERT INTO ingest_youtube_jobs VALUES (%s,%s,%s,'generating',%s,%s,NULL) "
                 "ON CONFLICT(document_id) DO UPDATE SET revision=excluded.revision,transcript=excluded.transcript,"
                 "status='generating',token=excluded.token,updated_at=excluded.updated_at,error=NULL",
                 (document_id,doc[1],transcript,token,time.time()))
    conn.execute('UPDATE ingest_documents SET projection_version=projection_version+1 WHERE id=%s', (document_id,))
    return {'revision': doc[1], 'token': token, 'transcript': transcript}


def finish(conn, document_id, *, revision, token, digest=None):
    row = conn.execute('SELECT source_type,source_id,title,url,published_at,media_json,revision FROM ingest_documents WHERE id=%s FOR UPDATE', (document_id,)).fetchone()
    job = conn.execute('SELECT revision,transcript,status,token FROM ingest_youtube_jobs WHERE document_id=%s', (document_id,)).fetchone()
    if not row or row[6] != revision or not job or (job[0],job[2],job[3]) != (revision,'generating',token):
        return False
    if digest is None:
        conn.execute("UPDATE ingest_youtube_jobs SET status='failed',token=NULL,updated_at=%s,error=%s WHERE document_id=%s",
                     (time.time(),'AI 정리본을 생성하지 못했습니다.',document_id))
        conn.execute('UPDATE ingest_documents SET projection_version=projection_version+1 WHERE id=%s', (document_id,))
        return True
    body = _digest_body(digest, job[1])
    updated = store_document(conn, source_type=row[0],source_id=row[1],title=row[2],url=row[3],
                             published_at=row[4],media=row[5],raw_content=body,markdown=body,digest_status='ok')
    conn.execute("UPDATE ingest_youtube_jobs SET revision=%s,status='ok',token=NULL,updated_at=%s,error=NULL WHERE document_id=%s",
                 (updated['revision'],time.time(),document_id))
    return True
