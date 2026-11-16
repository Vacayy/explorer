"""Run a legacy computation that adds documents on a private projection copy (single-path candidate).

Knowledge injection and the company web profile store new documents (and their graph rows) besides
their own result rows. The unchanged legacy function runs on a copy made with SQLite's page-streaming
backup (constant memory), borrowing it as its database connection, one such computation at a time.
Only rows above the copy's starting ids are published, in one transaction: documents through the
new-document path, result rows as row overrides. The copy is always removed; a copy left by a process
that died mid-way is removed by the next run.
"""
import sqlite3
import uuid
from pathlib import Path

from pipeline.postgres_graph_fixture import _guard

LOCK = 'copy-compute'
DOCUMENT_FLOORS = ('raw_documents', 'entities', 'entity_keywords', 'entity_relations')


def run(projection, factory, compute, *, results, source, before_commit=None):
    """`compute(work)` runs the legacy function; `results` maps result tables to (column, floor table):
    new rows are those whose column is above the floor table's starting max id. `before_commit(pg, work)`
    may add to the publishing transaction. Returns compute's result."""
    from pipeline import postgres_owner_overrides as overrides
    from pipeline.postgres_collected_documents_fixture import publish
    from pipeline.postgres_legacy_projection import write_connection_var
    from pipeline.postgres_usage_gate import require_signed_in
    from routers.postgres_owner_legacy_fixture import _Borrowed
    require_signed_in()  # an anonymous request is refused before the copy (the model call comes after it)
    directory = Path(projection.directory)
    work_path = directory / f'copy-{uuid.uuid4().hex}.db'
    lock = factory()
    lock.autocommit = True
    lock.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))', (LOCK,))
    work = None
    try:
        for leftover in directory.glob('copy-*.db'):  # holding the lock, no other run uses one
            leftover.unlink(missing_ok=True)
        source_db = sqlite3.connect(f'file:{projection.path()}?mode=ro', uri=True)
        work = sqlite3.connect(work_path, check_same_thread=False)
        try:
            source_db.backup(work, pages=256)
        finally:
            source_db.close()
        work.row_factory = sqlite3.Row
        floor_tables = {*DOCUMENT_FLOORS, *(floor for _, floor in results.values())}
        floors = {table: work.execute(f'SELECT COALESCE(max(id),0) FROM {table}').fetchone()[0] for table in floor_tables}
        token = write_connection_var.set(_Borrowed(work))
        try:
            result = compute(work)
        finally:
            write_connection_var.reset(token)
        work.commit()
        added = {table: {overrides._key(table, row): dict(row) for row in work.execute(
                     f'SELECT * FROM {table} WHERE {column} > ?', (floors[floor],))}
                 for table, (column, floor) in results.items()}
        with factory() as pg, pg.transaction():
            _guard(pg)
            publish(pg, work, document_floor=floors['raw_documents'], entity_floor=floors['entities'],
                    keyword_floor=floors['entity_keywords'], relation_floor=floors['entity_relations'])
            overrides.apply(pg, {table: {} for table in added}, added, source=source)
            if before_commit is not None:
                before_commit(pg, work)
        return result
    finally:
        if work is not None:
            work.close()
        work_path.unlink(missing_ok=True)
        lock.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (LOCK,))
        lock.close()
