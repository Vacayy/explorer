"""Knowledge injection (POST /api/spine/knowledge) on the single-path candidate.

The unchanged legacy `inject_knowledge` writes a vault note, stores it as a note document
(summary model call, entity links) and registers user knowledge (knowledge, its entities and
evidence, falsifiers). Here it runs on a private copy of the projection, made with SQLite's
page-streaming backup, one injection at a time. Only rows above the copy's starting ids are
published (new-document path for the note and its graph rows, row overrides for knowledge), in
one transaction; the note file is written to a staging folder and moved into the candidate-only
notes folder after that transaction commits. On any failure the copy and the staged file are removed.
"""
import hashlib
import os
import shutil
import sqlite3
import uuid
from pathlib import Path

from pipeline.postgres_graph_fixture import _guard

LOCK = 'knowledge-inject'
FLOORS = ('raw_documents', 'entities', 'entity_keywords', 'entity_relations', 'knowledge', 'knowledge_evidence',
          'knowledge_falsifiers')


def inject(projection, factory, notes_dir, content, epistemic, rationale, source):
    from pipeline import knowledge, postgres_owner_overrides as overrides
    from pipeline.postgres_collected_documents_fixture import publish
    from pipeline.postgres_legacy_projection import write_connection_var
    from routers.postgres_owner_legacy_fixture import _Borrowed
    notes_dir = Path(notes_dir)
    tag = uuid.uuid4().hex
    work_path = Path(projection.directory) / f'inject-{tag}.db'
    staging = notes_dir / f'.staging-{tag}'
    lock = factory()
    lock.autocommit = True
    lock.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (LOCK,))
    original_vault = knowledge.VAULT_PATH
    work = None
    # Holding the lock, no other injection runs: anything left here is from a process that died mid-way.
    for leftover in Path(projection.directory).glob('inject-*.db'):
        leftover.unlink(missing_ok=True)
    for leftover in notes_dir.glob('.staging-*'):
        shutil.rmtree(leftover, ignore_errors=True)
    try:
        source_db = sqlite3.connect(f'file:{projection.path()}?mode=ro', uri=True)
        work = sqlite3.connect(work_path, check_same_thread=False)
        try:
            source_db.backup(work, pages=256)  # page-streaming copy, constant memory
        finally:
            source_db.close()
        work.row_factory = sqlite3.Row
        floors = {table: work.execute(f'SELECT COALESCE(max(id),0) FROM {table}').fetchone()[0] for table in FLOORS}
        (staging / 'notes' / 'injected').mkdir(parents=True)
        knowledge.VAULT_PATH = staging  # the note lands in staging/notes/injected; source_id stays 'injected/<file>'
        token = write_connection_var.set(_Borrowed(work))
        try:
            result = knowledge.inject_knowledge(content, epistemic, rationale, source)
        finally:
            write_connection_var.reset(token)
        work.commit()
        staged = sorted((staging / 'notes' / 'injected').glob('*.md'))
        if len(staged) != 1:
            raise RuntimeError('Expected one injected note')
        rows = lambda table, where, value: {overrides._key(table, row): dict(row) for row in work.execute(
            f'SELECT * FROM {table} WHERE {where} > ?', (value,))}
        added = {'knowledge': rows('knowledge', 'id', floors['knowledge']),
                 'knowledge_evidence': rows('knowledge_evidence', 'id', floors['knowledge_evidence']),
                 'knowledge_falsifiers': rows('knowledge_falsifiers', 'id', floors['knowledge_falsifiers']),
                 'knowledge_entities': rows('knowledge_entities', 'knowledge_id', floors['knowledge'])}
        with factory() as pg, pg.transaction():
            _guard(pg)
            publish(pg, work, document_floor=floors['raw_documents'], entity_floor=floors['entities'],
                    keyword_floor=floors['entity_keywords'], relation_floor=floors['entity_relations'])
            overrides.apply(pg, {table: {} for table in added}, added, source='POST /api/spine/knowledge')
            note = staged[0]
            overrides.record_outputs(pg, 'POST /api/spine/knowledge', [
                ('vault_note', f'injected/{note.name}#sha256={hashlib.sha256(note.read_bytes()).hexdigest()}')])
        os.replace(note, notes_dir / note.name)  # the file becomes final only after the database commit
        return result
    finally:
        knowledge.VAULT_PATH = original_vault
        if work is not None:
            work.close()
        work_path.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
        lock.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (LOCK,))
        lock.close()
