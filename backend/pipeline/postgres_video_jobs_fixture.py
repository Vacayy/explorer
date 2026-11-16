"""Durable video-digest admission for a disposable single-path fixture.

Staging deliberately does not publish a digest before the document's derived
projections and search index can be updated consistently.
"""
import hashlib
import json
import time
from uuid import uuid4

from psycopg.types.json import Jsonb
from pipeline.postgres_graph_fixture import _guard


def initialize_video_jobs(target):
    _guard(target)
    if target.execute("SELECT to_regclass('video_digest_overlay_rows')").fetchone()[0] is None:
        raise ValueError('Video overlay is required')
    if target.execute("SELECT to_regclass('video_digest_work')").fetchone()[0] is not None:
        raise ValueError('Video work table already exists')
    target.execute("CREATE TABLE video_digest_work (document_id BIGINT PRIMARY KEY,token UUID NOT NULL, "
                   "status TEXT NOT NULL CHECK(status IN ('running','staged','failed','unknown','stale')), "
                   "source_hash TEXT NOT NULL,transcript TEXT NOT NULL,digest TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                   "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())")


def _hash(row):
    return hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def queue_video(connect, doc_id):
    if not isinstance(doc_id, int) or doc_id <= 0:
        raise ValueError('Invalid document id')
    with connect() as pg:
        _guard(pg)
        pg.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f'video-digest:{doc_id}',))
        row = pg.execute("SELECT row_ordinal,row_data FROM legacy_snapshot_rows "
                         "WHERE table_name='raw_documents' AND row_data->>'id'=%s", (str(doc_id),)).fetchone()
        if not row or row[1].get('source_type') != 'youtube':
            raise ValueError('유튜브 문서를 찾을 수 없습니다')
        doc = row[1]
        if doc.get('digest_status') == 'ok':
            return {'status': 'ok', 'token': None}
        work = pg.execute('SELECT status FROM video_digest_work WHERE document_id=%s FOR UPDATE', (doc_id,)).fetchone()
        if work and work[0] in ('running', 'staged', 'unknown'):
            return {'status': 'generating', 'token': None}
        previous = pg.execute("SELECT row_ordinal,row_data FROM legacy_snapshot_rows "
                              "WHERE table_name='youtube_digest_jobs' AND row_data->>'doc_id'=%s", (str(doc_id),)).fetchone()
        job = previous[1] if previous else None
        if job and job.get('status') == 'generating' and not work:
            # An inherited in-flight job might already have called a model.
            return {'status': 'interrupted', 'token': None}
        transcript = (job or {}).get('transcript') or doc.get('raw_content') or ''
        if len(transcript) < 100:
            raise ValueError('정리할 자막이 충분하지 않습니다')
        token = uuid4()
        ordinal = previous[0] if previous else -doc_id
        result = {'doc_id': doc_id, 'transcript': transcript, 'status': 'generating',
                  'token': str(token), 'updated_at': time.time(), 'error': None}
        pg.execute("INSERT INTO video_digest_overlay_rows VALUES('youtube_digest_jobs',%s,%s) "
                   "ON CONFLICT(table_name,row_ordinal) DO UPDATE SET row_data=excluded.row_data", (ordinal, Jsonb(result)))
        pg.execute("INSERT INTO video_digest_work(document_id,token,status,source_hash,transcript) VALUES(%s,%s,'running',%s,%s) "
                   "ON CONFLICT(document_id) DO UPDATE SET token=excluded.token,status='running',source_hash=excluded.source_hash, "
                   "transcript=excluded.transcript,digest=NULL,created_at=now(),updated_at=now()", (doc_id, token, _hash(doc), transcript))
        return {'status': 'generating', 'token': token, 'title': doc.get('title') or '', 'transcript': transcript}


def stage_video_result(connect, doc_id, token, digest):
    """Persist one result without changing the published document or retrying."""
    with connect() as pg:
        _guard(pg)
        pg.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f'video-digest:{doc_id}',))
        work = pg.execute('SELECT token,status,source_hash FROM video_digest_work WHERE document_id=%s FOR UPDATE', (doc_id,)).fetchone()
        if not work or work[0] != token or work[1] != 'running':
            return False
        row = pg.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' AND row_data->>'id'=%s", (str(doc_id),)).fetchone()
        if not row or _hash(row[0]) != work[2]:
            pg.execute("UPDATE video_digest_work SET status='stale',updated_at=now() WHERE document_id=%s", (doc_id,))
            return False
        if not digest or not digest.strip():
            pg.execute("UPDATE video_digest_work SET status='failed',updated_at=now() WHERE document_id=%s", (doc_id,))
            pg.execute("UPDATE video_digest_overlay_rows SET row_data=row_data || %s WHERE table_name='youtube_digest_jobs' AND row_data->>'doc_id'=%s",
                       (Jsonb({'status': 'failed', 'error': 'AI 정리본을 생성하지 못했습니다.', 'updated_at': time.time()}), str(doc_id)))
            return True
        pg.execute("UPDATE video_digest_work SET status='staged',digest=%s,updated_at=now() WHERE document_id=%s", (digest.strip(), doc_id))
        return True
