"""One projection build for the single-path preview, outside the API process.

The builder container runs this module every few seconds as a fresh process
(so each build's memory is returned): if the candidate's projection version
moved since the manifest, it builds a new SQLite projection (when only collected tables changed, at most every
COLLECTION_BUILD_SECONDS; pipeline.postgres_live_tables), re-embeds changed
documents, then atomically replaces `current.json` and `current.db`. The API
(`LegacyProjection(external=True)`) only switches to the file the manifest
names. Writes landing during a build are picked up by the next run, so bursts
coalesce into one more build.
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

import psycopg

from pipeline import postgres_live_tables
from pipeline.postgres_legacy_projection import build_projection, projection_version

KEEP = 2  # the current file and the one before it, for readers still on it
KEEP_SECONDS = 120  # and any written in the last two minutes (readers switch every 10s)
# Collected tables (not the live ones) show within this; the MacBook's chain also ran every 30 minutes.
COLLECTION_BUILD_SECONDS = int(os.environ.get('COLLECTION_BUILD_SECONDS', '900'))


def run(directory):
    directory = Path(directory)
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']

    factory = lambda: psycopg.connect(dsn, options=f'-c search_path={schema}')  # as the preview API connects

    manifest = directory / 'current.json'
    current = json.loads(manifest.read_text()) if manifest.exists() else None
    with factory() as pg:
        version = projection_version(pg)
        _live, collection = postgres_live_tables.versions(pg)
    if current and current['version'] == version:
        # Only collected tables changed: fold them into one rebuild at most every COLLECTION_BUILD_SECONDS.
        if collection is None or current.get('collection') == collection:
            return False
        if time.time() - manifest.stat().st_mtime < COLLECTION_BUILD_SECONDS:
            return False
    from pipeline.postgres_heavy_lock import try_lock
    held = factory()  # one heavy job at a time (pipeline.postgres_heavy_lock): busy → try again next cycle
    held.autocommit = True
    if not try_lock(held):
        held.close()
        print(json.dumps({'skipped': 'heavy lock busy'}), flush=True)
        return False
    try:
        return _build(factory, directory, current, collection)
    finally:
        held.close()  # releases the lock


def _build(factory, directory, current, collection):
    if current and (directory / current['file']).exists():
        # A build that died before its file was linked (memory, a restart) left that file; no reader ever had it, and
        # repeated failures must not fill the volume.
        linked = (directory / current['file']).stat().st_mtime
        for leftover in directory.glob('projection-*.db'):
            if leftover.name != current['file'] and leftover.stat().st_mtime > linked:
                leftover.unlink(missing_ok=True)
    started = time.monotonic()
    path, version, legacy_version = build_projection(factory, directory)
    refreshed = _reembed(factory)
    chunked = _rechunk(directory, path)
    for name, target in (('current.db', path.name), ('current.json', None)):
        temporary = directory / f'{name}-{uuid.uuid4().hex}'
        if target:
            temporary.symlink_to(target)
        else:
            temporary.write_text(json.dumps({'file': path.name, 'version': version, 'legacy_version': legacy_version,
                                             'reembedded': refreshed, 'collection': collection}))
        os.replace(temporary, directory / name)
    # Readers switch files every CHECK_SECONDS; back-to-back builds must not remove a file one may still be on.
    for old in sorted(directory.glob('projection-*.db'), key=lambda item: item.stat().st_mtime)[:-KEEP]:
        if time.time() - old.stat().st_mtime > KEEP_SECONDS:
            old.unlink(missing_ok=True)
    measure = {'seconds': round(time.monotonic() - started, 1), 'bytes': path.stat().st_size,
               'cause': 'collection' if current and current['version'] == version else 'change'}
    with open(directory / 'builds.jsonl', 'a') as log:  # rebuild count, time and size per day (PM 6938809334)
        log.write(json.dumps({'at': time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime()), **measure}) + '\n')
    print(json.dumps({'built': path.name, 'version': version, 'reembedded': len(refreshed), 'chunked': chunked, **measure}),
          flush=True)
    return True


def _reembed(factory):
    """Re-embed published documents whose content changed (the legacy recipe, local model)."""
    from pipeline.postgres_embedding_refresh_fixture import refresh, stale_documents
    from pipeline.search import _get_model, _serialize
    with factory() as pg:
        if not stale_documents(pg):
            return []  # no model load when nothing changed
        return refresh(pg, _get_model(local_files_only=True), _serialize)


def _rechunk(directory, path):
    """New and revised documents into the chunk index the compute worker searches (AI-answer evidence)."""
    from pipeline.postgres_chunk_index import refresh
    if not (directory / 'chunks.db').exists():
        return None
    result = refresh(directory / 'chunks.db', path)
    return {key: result.get(key) for key in ('docs', 'chunks', 'orphans')}


def refresh_document_meta():
    """The text-free document table (pipeline.postgres_document_meta, migration 20) follows the ledger version, before
    the build so it is not held behind one. Its own connection and time limit; a failure is logged and never stops
    the build (readers use the ledger view while the table is not current)."""
    from pipeline import postgres_document_meta as meta
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
    try:
        with psycopg.connect(dsn, autocommit=True, options=f'-c search_path={schema} -c statement_timeout=60000') as pg:
            # One publication moves the version more than once (the document, then its enrichments and links): a
            # refresh finished between them would leave the table one version behind until the next cycle, after a
            # whole build (2 min on 2026-11-22). Refresh again while the version moved, at most three times.
            for _ in range(3):
                done = meta.refresh(pg) if meta.exists(pg) else None
                if not done:
                    break
                print(json.dumps({'document_meta': done, 'at': time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}),
                      flush=True)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({'document_meta_failed': f'{type(exc).__name__}: {str(exc)[:160]}'}), flush=True)


if __name__ == '__main__':
    refresh_document_meta()
    run(sys.argv[1] if len(sys.argv) > 1 else '/projection')
