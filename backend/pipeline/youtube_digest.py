"""Durable, deduplicated admission for on-demand video digests; GET never generates."""
import time
import uuid
from fastapi import HTTPException
from database import get_connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS youtube_digest_jobs (
    doc_id INTEGER PRIMARY KEY REFERENCES raw_documents(id) ON DELETE CASCADE,
    transcript TEXT NOT NULL,
    status TEXT NOT NULL,
    token TEXT NOT NULL,
    updated_at REAL NOT NULL,
    error TEXT
);
"""
STALE_SECONDS = 3600


def fields(conn, row):
    if row['source_type'] != 'youtube':
        return {}
    job = conn.execute('SELECT * FROM youtube_digest_jobs WHERE doc_id=?', (row['id'],)).fetchone()
    done = row['digest_status'] == 'ok'
    status = 'ok' if done else (job['status'] if job else row['digest_status'] or 'pending')
    if status == 'generating' and time.time() - job['updated_at'] > STALE_SECONDS:
        status = 'interrupted'
    return dict(digest_status=status,
                digest_error=job['error'] if job else None,
                video_digest=(row['markdown'] or row['raw_content']) if done else None,
                transcript=job['transcript'] if job else (None if done else row['raw_content']))


def queue(doc_id):
    conn = get_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT * FROM raw_documents WHERE id=? AND source_type='youtube'", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, '유튜브 문서를 찾을 수 없습니다')
        if row['digest_status'] == 'ok':
            return {'status': 'ok', 'token': None}
        job = conn.execute('SELECT * FROM youtube_digest_jobs WHERE doc_id=?', (doc_id,)).fetchone()
        if job and job['status'] == 'generating' and time.time() - job['updated_at'] <= STALE_SECONDS:
            return {'status': 'generating', 'token': None}
        transcript = job['transcript'] if job else row['raw_content'] or ''
        if len(transcript) < 100:
            raise HTTPException(422, '정리할 자막이 충분하지 않습니다')
        token = uuid.uuid4().hex
        conn.execute('''INSERT INTO youtube_digest_jobs VALUES(?,?,'generating',?,?,NULL)
            ON CONFLICT(doc_id) DO UPDATE SET status='generating',token=excluded.token,
            updated_at=excluded.updated_at,error=NULL''', (doc_id, transcript, token, time.time()))
        conn.commit()
        return {'status': 'generating', 'token': token}
    finally:
        conn.close()


def execute(doc_id, token):
    from pipeline.connectors.youtube import _digest_stored
    error = None
    try:
        ok = _digest_stored(doc_id)
        if not ok:
            error = 'AI 정리본을 생성하지 못했습니다. Claude 인증·사용량 상태를 확인한 뒤 다시 시도해 주세요.'
    except Exception:
        ok = False
        error = 'AI 정리 작업이 중단되었습니다. 잠시 후 다시 시도해 주세요.'
    conn = get_connection()
    try:
        conn.execute('''UPDATE youtube_digest_jobs SET status=?,error=?,updated_at=?
            WHERE doc_id=? AND token=?''', ('ok' if ok else 'failed', error, time.time(), doc_id, token))
        conn.commit()
    finally:
        conn.close()
    return ok
