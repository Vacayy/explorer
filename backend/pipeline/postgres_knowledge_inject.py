"""Knowledge injection (POST /api/spine/knowledge) on the single-path candidate.

The unchanged legacy `inject_knowledge` writes a vault note, stores it as a note document
(summary model call, entity links) and registers user knowledge (knowledge, its entities and
evidence, falsifiers). It runs as a private-copy computation (`postgres_copy_compute`); the note
file is written to a staging folder and moved into the candidate-only notes folder after the
publishing transaction commits. On any failure the staged file is removed.
"""
import hashlib
import os
import shutil
import uuid
from pathlib import Path

from pipeline import postgres_copy_compute

RESULTS = {'knowledge': ('id', 'knowledge'), 'knowledge_evidence': ('id', 'knowledge_evidence'),
           'knowledge_falsifiers': ('id', 'knowledge_falsifiers'), 'knowledge_entities': ('knowledge_id', 'knowledge')}
SOURCE = 'POST /api/spine/knowledge'


def inject(projection, factory, notes_dir, content, epistemic, rationale, source):
    from pipeline import knowledge, postgres_owner_overrides as overrides
    notes_dir = Path(notes_dir)
    for leftover in notes_dir.glob('.staging-*'):  # left by a process that died mid-way
        shutil.rmtree(leftover, ignore_errors=True)
    staging = notes_dir / f'.staging-{uuid.uuid4().hex}'
    original_vault = knowledge.VAULT_PATH
    staged = []

    def compute(work):
        (staging / 'notes' / 'injected').mkdir(parents=True)
        knowledge.VAULT_PATH = staging  # the note lands in staging/notes/injected; source_id stays 'injected/<file>'
        result = knowledge.inject_knowledge(content, epistemic, rationale, source)
        staged.extend(sorted((staging / 'notes' / 'injected').glob('*.md')))
        if len(staged) != 1:
            raise RuntimeError('Expected one injected note')
        return result

    def record_note(pg, work):
        note = staged[0]
        overrides.record_outputs(pg, SOURCE, [
            ('vault_note', f'injected/{note.name}#sha256={hashlib.sha256(note.read_bytes()).hexdigest()}')])

    try:
        result = postgres_copy_compute.run(projection, factory, compute, results=RESULTS, source=SOURCE,
                                           before_commit=record_note)
        os.replace(staged[0], notes_dir / staged[0].name)  # the file becomes final only after the database commit
        return result
    finally:
        knowledge.VAULT_PATH = original_vault
        shutil.rmtree(staging, ignore_errors=True)
