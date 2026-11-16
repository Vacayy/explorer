"""Keyword alias approval with its back-linking on the single-path candidate (POST /api/spine/keywords/{id}/approve).

The legacy handler marks the alias active and links every existing document that mentions it (`entity_links`).
Here it runs unchanged on a private copy of the projection in the compute worker (a full-corpus scan, too heavy
for the API); the documents whose links changed are published as document revisions (`publish_revisions`,
three-way merge, conflicts kept), and the alias row as a row override, in one PG transaction. The API waits
for the job so the screen gets the legacy answer (`retro_linked_docs`).
"""
import sqlite3
import uuid
from pathlib import Path

from pipeline.postgres_graph_fixture import _guard

LOCK = 'copy-compute'  # one private projection copy at a time (as postgres_copy_compute)


def backfill(factory, projection_path, keyword_id):
    from pipeline import postgres_owner_overrides as overrides
    from pipeline.postgres_collected_changes_fixture import capture, changed_documents, publish_revisions
    from routers.spine_keywords import _retro_link
    source = f'POST /api/spine/keywords/{keyword_id}/approve'
    directory = Path(projection_path).parent
    work_path = directory / f'copy-{uuid.uuid4().hex}.db'
    lock = factory()
    lock.autocommit = True
    lock.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))', (LOCK,))
    origin = work = None
    try:
        for leftover in directory.glob('copy-*.db'):  # holding the lock, no other run uses one
            leftover.unlink(missing_ok=True)
        origin = sqlite3.connect(f'file:{projection_path}?mode=ro', uri=True)
        work = sqlite3.connect(work_path)
        origin.backup(work, pages=256)
        work.row_factory = origin.row_factory = sqlite3.Row
        before_row = work.execute('SELECT * FROM entity_keywords WHERE id=?', (keyword_id,)).fetchone()
        if before_row is None:
            return {'status': 'not_found'}
        floor = work.execute('SELECT COALESCE(max(id),0) FROM raw_documents').fetchone()[0]
        documents = capture(work, floor)
        # The legacy approve_keyword body, on the copy.
        work.execute("UPDATE entity_keywords SET status='active' WHERE id=?", (keyword_id,))
        linked = _retro_link(work, before_row['entity_id'], before_row['keyword'])
        work.commit()
        after_row = work.execute('SELECT * FROM entity_keywords WHERE id=?', (keyword_id,)).fetchone()
        changed, removed = changed_documents(work, documents, floor)
        if removed:
            raise RuntimeError('Documents disappeared from the private copy')
        key = overrides._key('entity_keywords', before_row)
        with factory() as pg, pg.transaction():
            _guard(pg)
            published = publish_revisions(pg, work, origin, changed, run_id=source)
            overrides.apply(pg, {'entity_keywords': {key: dict(before_row)}}, {'entity_keywords': {key: dict(after_row)}},
                            source=source)
        return {'status': 'done', 'keyword': before_row['keyword'], 'retro_linked_docs': linked,
                'published': len(published['published']), 'kept': [list(item) for item in published['kept']]}
    finally:
        for conn in (work, origin):
            if conn is not None:
                conn.close()
        work_path.unlink(missing_ok=True)
        lock.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (LOCK,))
        lock.close()


def create_router(factory, *, wait_seconds=300):
    import time
    from fastapi import APIRouter, HTTPException
    from pipeline.postgres_retrieval_jobs import enqueue
    router = APIRouter(prefix='/api/spine/keywords')

    @router.post('/{keyword_id}/approve')
    def approve(keyword_id: int):
        with factory() as conn:
            ident = enqueue(conn, 'keyword_backfill', f'keyword {keyword_id}', {'keyword_id': keyword_id})
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            time.sleep(.5)
            with factory() as conn:
                status, result, error = conn.execute('SELECT status,result,error FROM retrieval_jobs WHERE id=%s',
                                                     (ident,)).fetchone()
            if status == 'failed':
                raise HTTPException(503, '소급 링크를 반영하지 못했습니다')
            if status == 'done':
                if result['status'] == 'not_found':
                    raise HTTPException(404, '키워드를 찾을 수 없습니다')
                return {'keyword': result['keyword'], 'retro_linked_docs': result['retro_linked_docs']}
        # Still queued or running: the job finishes on its own; the answer would only arrive too late.
        raise HTTPException(503, '소급 링크가 아직 진행 중입니다. 잠시 뒤 다시 확인해 주세요.')

    return router
