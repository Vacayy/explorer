"""Durable video-digest admission for a disposable single-path fixture.

Staging deliberately does not publish a digest before the document's derived
projections and search index can be updated consistently.
"""
import hashlib
import json
import time
from copy import deepcopy
from uuid import uuid4

from psycopg.types.json import Jsonb
from pipeline.postgres_graph_fixture import _guard
from pipeline.youtube_digest import STALE_SECONDS


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


def initialize_video_analysis(target):
    _guard(target)
    if target.execute("SELECT to_regclass('video_digest_work')").fetchone()[0] is None:
        raise ValueError('Video work table is required')
    if target.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() "
                      "AND table_name='video_digest_work' AND column_name='analysis_status'").fetchone():
        raise ValueError('Video analysis already initialized')
    target.execute("ALTER TABLE video_digest_work ADD COLUMN analysis_status TEXT NOT NULL DEFAULT 'pending' "
                   "CHECK(analysis_status IN ('pending','running','completed','unknown','stale'))")
    target.execute('ALTER TABLE video_digest_work ADD COLUMN analysis_token UUID')
    target.execute('ALTER TABLE video_digest_work ADD COLUMN analysis JSONB')


def enable_video_publication(target):
    _guard(target)
    definition = target.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid=to_regclass('video_digest_work') AND conname='video_digest_work_status_check'").fetchone()
    if not definition or 'published' in definition[0]:
        raise ValueError('Unexpected or already enabled video publication')
    target.execute('ALTER TABLE video_digest_work DROP CONSTRAINT video_digest_work_status_check')
    target.execute("ALTER TABLE video_digest_work ADD CONSTRAINT video_digest_work_status_check "
                   "CHECK(status IN ('running','staged','failed','unknown','stale','published'))")


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
        work = pg.execute('SELECT status,analysis_status,token,transcript,extract(epoch FROM now()-updated_at) > %s '
                          'FROM video_digest_work WHERE document_id=%s FOR UPDATE', (STALE_SECONDS, doc_id)).fetchone()
        if work:
            status, analysis, token, transcript, old = work
            resume = None
            if status == 'staged' and analysis == 'completed':
                resume = 'publish'  # the saved digest and analysis are reused without a model call
            elif status == 'staged' and analysis in ('pending', 'running', 'unknown') and (old or analysis == 'unknown'):
                resume = 'analysis'  # the saved digest is reused; only the analysis runs again
            elif not old and (status == 'running' or (status == 'staged' and analysis in ('pending', 'running'))):
                return {'status': 'generating', 'token': None}
            elif status == 'unknown' and not old:
                # A digest call may have finished unseen; allow a new call only after the existing stale window.
                return {'status': 'interrupted', 'token': None}
            if resume:
                pg.execute("UPDATE video_digest_work SET analysis_status=CASE WHEN %s='analysis' THEN 'pending' ELSE analysis_status END, "
                           "analysis_token=CASE WHEN %s='analysis' THEN NULL ELSE analysis_token END,updated_at=now() "
                           "WHERE document_id=%s", (resume, resume, doc_id))
                pg.execute("UPDATE video_digest_overlay_rows SET row_data=row_data || %s "
                           "WHERE table_name='youtube_digest_jobs' AND row_data->>'doc_id'=%s",
                           (Jsonb({'status': 'generating', 'error': None, 'updated_at': time.time()}), str(doc_id)))
                return {'status': 'generating', 'token': token, 'resume': resume,
                        'title': doc.get('title') or '', 'transcript': transcript}
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
                   "transcript=excluded.transcript,digest=NULL,analysis_status='pending',analysis_token=NULL,analysis=NULL, "
                   "created_at=now(),updated_at=now()", (doc_id, token, _hash(doc), transcript))
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


def run_video_job(connect, doc_id, token, title, transcript, *, run_llm):
    """Run the existing digest prompt once and stage, never auto-retry."""
    from pipeline.connectors.youtube import digest_transcript
    digest = digest_transcript(title, transcript, run_llm=run_llm, max_attempts=1, quiet=True)
    if digest is not None:
        return {'status': 'staged' if stage_video_result(connect, doc_id, token, digest) else 'stale'}
    with connect() as pg:
        _guard(pg)
        pg.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f'video-digest:{doc_id}',))
        changed = pg.execute("UPDATE video_digest_work SET status='unknown',updated_at=now() "
                             "WHERE document_id=%s AND token=%s AND status='running'", (doc_id, token))
        if changed.rowcount:
            pg.execute("UPDATE video_digest_overlay_rows SET row_data=row_data || %s "
                       "WHERE table_name='youtube_digest_jobs' AND row_data->>'doc_id'=%s",
                       (Jsonb({'status': 'interrupted', 'error': '정리 결과를 확인하지 못했습니다.', 'updated_at': time.time()}), str(doc_id)))
    return {'status': 'unknown' if changed.rowcount else 'stale'}


def mark_video_interrupted(connect, doc_id, token):
    """Expose an incomplete staged job without discarding its saved result."""
    with connect() as pg:
        _guard(pg)
        pg.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f'video-digest:{doc_id}',))
        work = pg.execute('SELECT token,status FROM video_digest_work WHERE document_id=%s FOR UPDATE', (doc_id,)).fetchone()
        if not work or work[0] != token or work[1] == 'published':
            return False
        pg.execute("UPDATE video_digest_overlay_rows SET row_data=row_data || %s "
                   "WHERE table_name='youtube_digest_jobs' AND row_data->>'doc_id'=%s",
                   (Jsonb({'status': 'interrupted', 'error': '정리 결과 확인 또는 반영이 필요합니다.', 'updated_at': time.time()}), str(doc_id)))
        return True


def run_video_analysis(connect, doc_id, *, analyze):
    """Analyze one staged digest once; keep unknown results for reconciliation."""
    from pipeline.connectors.youtube import _digest_body
    with connect() as pg:
        _guard(pg)
        pg.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f'video-digest:{doc_id}',))
        work = pg.execute('SELECT token,status,source_hash,transcript,digest,analysis_status FROM video_digest_work '
                          'WHERE document_id=%s FOR UPDATE', (doc_id,)).fetchone()
        if not work or work[1] != 'staged' or work[5] != 'pending':
            return {'status': 'unavailable'}
        row = pg.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' "
                         "AND row_data->>'id'=%s", (str(doc_id),)).fetchone()
        if not row or _hash(row[0]) != work[2]:
            pg.execute("UPDATE video_digest_work SET analysis_status='stale',updated_at=now() WHERE document_id=%s", (doc_id,))
            return {'status': 'stale'}
        analysis_token = uuid4()
        pg.execute("UPDATE video_digest_work SET analysis_status='running',analysis_token=%s,updated_at=now() WHERE document_id=%s",
                   (analysis_token, doc_id))
        title, body = row[0].get('title') or '', _digest_body(work[4], work[3])
    try:
        analysis = analyze(title, body)
        if not isinstance(analysis, dict) or not isinstance(analysis.get('model'), str) or not analysis['model']:
            raise ValueError('Invalid analysis result')
    except Exception:
        with connect() as pg:
            _guard(pg)
            pg.execute("UPDATE video_digest_work SET analysis_status='unknown',updated_at=now() "
                       "WHERE document_id=%s AND analysis_token=%s AND analysis_status='running'", (doc_id, analysis_token))
        return {'status': 'unknown'}
    with connect() as pg:
        _guard(pg)
        pg.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f'video-digest:{doc_id}',))
        current = pg.execute('SELECT token,status,source_hash,analysis_token,analysis_status FROM video_digest_work '
                             'WHERE document_id=%s FOR UPDATE', (doc_id,)).fetchone()
        row = pg.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' "
                         "AND row_data->>'id'=%s", (str(doc_id),)).fetchone()
        if not current or current != (work[0], 'staged', work[2], analysis_token, 'running') or not row or _hash(row[0]) != work[2]:
            pg.execute("UPDATE video_digest_work SET analysis_status='stale',updated_at=now() "
                       "WHERE document_id=%s AND analysis_token=%s AND analysis_status='running'", (doc_id, analysis_token))
            return {'status': 'stale'}
        pg.execute("UPDATE video_digest_work SET analysis_status='completed',analysis=%s,updated_at=now() WHERE document_id=%s",
                   (Jsonb(analysis), doc_id))
        return {'status': 'completed'}


def _graph_links(pg, doc_id, title, body, analysis):
    """Reuse the legacy linker on a private snapshot and return its graph changes."""
    from pipeline.postgres_urgent_selection_fixture import open_snapshot
    from pipeline.store import _link
    root, _, _ = open_snapshot(pg, ('entities', 'entity_keywords', 'entity_relations'))
    try:
        ddl = pg.execute("SELECT schema_sql FROM legacy_snapshot_tables WHERE table_name='entity_links'").fetchone()
        if not ddl:
            raise ValueError('Entity-link schema is missing')
        root.execute(ddl[0])
        tables = ('entities', 'entity_keywords', 'entity_relations')
        before = {name: {row[0] for row in root.execute('SELECT id FROM ' + name)} for name in tables}
        _link(root, doc_id, title, body, analysis)
        added = {name: [dict(row) for row in root.execute('SELECT * FROM ' + name + ' ORDER BY id')
                        if row['id'] not in before[name]] for name in tables}
        rows = root.execute('SELECT l.entity_id,l.link_type,l.confidence,e.type,e.name,e.aliases '
                            'FROM entity_links l JOIN entities e ON e.id=l.entity_id ORDER BY l.id').fetchall()
        return ([{'entity_id': r[0], 'link_type': r[1], 'confidence': r[2],
                  'type': r[3], 'name': r[4], 'aliases': r[5]} for r in rows], added)
    finally:
        root.close()


def publish_video_result(connect, doc_id, *, search_lock, invalidate_search):
    """Atomically publish a staged digest and its fresh graph analysis."""
    from pipeline.connectors.youtube import _digest_body
    from pipeline.postgres_graph_fixture import GRAPH_LOCK
    from pipeline.store import _hash as content_hash
    if not callable(invalidate_search):
        raise ValueError('Search invalidation is required')
    with search_lock:
        with connect() as pg:
            _guard(pg)
            pg.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f'video-digest:{doc_id}',))
            pg.execute('SELECT pg_advisory_xact_lock(%s)', (GRAPH_LOCK,))
            work = pg.execute('SELECT token,status,source_hash,transcript,digest,analysis_status,analysis '
                              'FROM video_digest_work WHERE document_id=%s FOR UPDATE', (doc_id,)).fetchone()
            if not work or work[1] != 'staged' or work[5] != 'completed':
                raise ValueError('Staged digest and completed analysis are required')
            source = pg.execute("SELECT row_ordinal,row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' "
                                "AND row_data->>'id'=%s", (str(doc_id),)).fetchone()
            job = pg.execute("SELECT row_ordinal,row_data FROM legacy_snapshot_rows WHERE table_name='youtube_digest_jobs' "
                             "AND row_data->>'doc_id'=%s", (str(doc_id),)).fetchone()
            if not source or _hash(source[1]) != work[2] or not job or job[1].get('token') != str(work[0]):
                raise ValueError('Video source or job changed')
            analysis = work[6]
            if not isinstance(analysis, dict) or not isinstance(analysis.get('model'), str) or not analysis['model']:
                raise ValueError('Fresh analysis is required')
            if not isinstance(analysis.get('summary'), str) or not analysis['summary'].strip():
                raise ValueError('Fresh summary is required')
            body = _digest_body(work[4], work[3])
            links, additions = _graph_links(pg, doc_id, source[1].get('title') or '', body, analysis)
            if len(links) >= 10000 or not 0 < doc_id < 10**12:
                raise ValueError('Unsupported video or link count')
            projection = pg.execute('SELECT detail_document FROM document_projection WHERE id=%s AND source_type=\'youtube\'', (doc_id,)).fetchone()
            listing = pg.execute('SELECT ordinal,list_document FROM document_list_projection WHERE document_id=%s ORDER BY ordinal LIMIT 1', (doc_id,)).fetchone()
            if not projection:
                raise ValueError('Video detail projection is missing')
            stamp = pg.execute("SELECT to_char(timezone('utc',now()),'YYYY-MM-DD HH24:MI:SS')").fetchone()[0]
            raw = deepcopy(source[1]); raw.update({'raw_content': body, 'markdown': body, 'content_hash': content_hash(body),
                                                  'digest_status': 'ok', 'fetched_at': stamp})
            updated_job = deepcopy(job[1]); updated_job.update({'status': 'ok', 'error': None, 'updated_at': time.time()})
            detail = deepcopy(projection[0]); detail.update({'content': body, 'summary': analysis['summary'],
                'enrich_model': analysis['model'], 'entities': links, 'digest_status': 'ok',
                'digest_error': None, 'video_digest': body, 'transcript': work[3]})
            list_ordinal = listing[0] if listing else -doc_id
            listed = deepcopy(listing[1] if listing else detail)
            listed.update({'content': body, 'summary': analysis['summary'], 'enrich_model': analysis['model'],
                           'entities': links, 'digest_status': None, 'digest_error': None, 'video_digest': None, 'transcript': None})
            for table in ('entities', 'entity_keywords'):
                for row in additions[table]:
                    if not row.get('id') or row['id'] < 1:
                        raise ValueError('New graph identity is invalid')
                    pg.execute('INSERT INTO video_digest_overlay_rows VALUES(%s,%s,%s)',
                               (table, -row['id'], Jsonb(row)))
            ordinal = pg.execute("SELECT COALESCE(max(row_ordinal),-1)+1 FROM question_graph_overlay_rows WHERE table_name='entity_relations'").fetchone()[0]
            for position, row in enumerate(additions['entity_relations']):
                if not row.get('id') or row['id'] < 1:
                    raise ValueError('New relationship identity is invalid')
                pg.execute("INSERT INTO question_graph_overlay_rows VALUES('entity_relations',%s,%s)", (ordinal + position, Jsonb(row)))
                pg.execute('INSERT INTO question_graph_overlay_relations(id,source_row) VALUES(%s,%s)', (row['id'], Jsonb(row)))
            collected = pg.execute("SELECT to_regclass('collected_document_projection')").fetchone()[0] is not None and \
                pg.execute('SELECT EXISTS(SELECT 1 FROM collected_document_projection WHERE id=%s)', (doc_id,)).fetchone()[0]
            if collected:  # its rows are not under the base override; replace them where they live
                pg.execute('UPDATE collected_document_projection SET detail_document=%s WHERE id=%s', (Jsonb(detail), doc_id))
                pg.execute('UPDATE collected_document_list_projection SET list_document=%s WHERE document_id=%s',
                           (Jsonb(listed), doc_id))
            else:  # the override matches the base view's own ordinal, before any collected-order scaling
                from pipeline.postgres_collected_documents_fixture import order_scale
                pg.execute('INSERT INTO video_projection_overrides VALUES(%s,%s,%s,%s) '
                           'ON CONFLICT(document_id) DO UPDATE SET detail_document=excluded.detail_document, '
                           'list_ordinal=excluded.list_ordinal,list_document=excluded.list_document',
                           (doc_id, Jsonb(detail), list_ordinal // order_scale(pg) if listing else list_ordinal, Jsonb(listed)))
            for kind, ordinal, value in (('raw_documents', source[0], raw), ('youtube_digest_jobs', job[0], updated_job)):
                pg.execute('INSERT INTO video_digest_overlay_rows VALUES(%s,%s,%s) ON CONFLICT(table_name,row_ordinal) '
                           'DO UPDATE SET row_data=excluded.row_data', (kind, ordinal, Jsonb(value)))
            pg.execute("DELETE FROM video_digest_overlay_rows WHERE table_name IN ('enrichments','entity_links') AND row_data->>'doc_id'=%s", (str(doc_id),))
            enrichment = {'id': -doc_id, 'doc_id': doc_id, 'summary': analysis['summary'], 'sentiment': analysis.get('sentiment'),
                          'model': analysis['model'], 'content_hash': raw['content_hash'], 'enriched_at': stamp,
                          'time_orientation': analysis.get('time_orientation'), 'reference_period': analysis.get('reference_period'), 'causal_extracted_at': None}
            pg.execute("INSERT INTO video_digest_overlay_rows VALUES('enrichments',%s,%s)", (-doc_id, Jsonb(enrichment)))
            for position, link in enumerate(links):
                ident = -(doc_id * 10000 + position + 1)
                data = {'id': ident, 'doc_id': doc_id, 'entity_id': link['entity_id'],
                        'link_type': link['link_type'], 'confidence': link['confidence']}
                pg.execute("INSERT INTO video_digest_overlay_rows VALUES('entity_links',%s,%s)", (ident, Jsonb(data)))
            pg.execute("UPDATE video_digest_work SET status='published',updated_at=now() WHERE document_id=%s", (doc_id,))
            invalidate_search()
        return {'status': 'published', 'document_id': doc_id, 'links': len(links)}
