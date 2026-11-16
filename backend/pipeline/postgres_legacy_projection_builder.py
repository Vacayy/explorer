"""One projection build for the single-path preview, outside the API process.

The builder container runs this module every few seconds as a fresh process
(so each build's memory is returned): if the candidate's projection version
moved since the manifest, it builds a new SQLite projection, re-embeds changed
documents, then atomically replaces `current.json` and `current.db`. The API
(`LegacyProjection(external=True)`) only switches to the file the manifest
names. Writes landing during a build are picked up by the next run, so bursts
coalesce into one more build.
"""
import json
import os
import sys
import uuid
from pathlib import Path

import psycopg

from pipeline.postgres_legacy_projection import build_projection, projection_version

KEEP = 2  # the current file and the one before it, for readers still on it


def run(directory):
    directory = Path(directory)
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']

    factory = lambda: psycopg.connect(dsn, options=f'-c search_path={schema}')  # as the preview API connects

    manifest = directory / 'current.json'
    current = json.loads(manifest.read_text()) if manifest.exists() else None
    with factory() as pg:
        version = projection_version(pg)
    if current and current['version'] == version:
        return False
    path, version, legacy_version = build_projection(factory, directory)
    refreshed = _reembed(factory)
    chunked = _rechunk(directory, path)
    for name, target in (('current.db', path.name), ('current.json', None)):
        temporary = directory / f'{name}-{uuid.uuid4().hex}'
        if target:
            temporary.symlink_to(target)
        else:
            temporary.write_text(json.dumps({'file': path.name, 'version': version, 'legacy_version': legacy_version,
                                             'reembedded': refreshed}))
        os.replace(temporary, directory / name)
    for old in sorted(directory.glob('projection-*.db'), key=lambda item: item.stat().st_mtime)[:-KEEP]:
        old.unlink(missing_ok=True)
    print(json.dumps({'built': path.name, 'version': version, 'reembedded': len(refreshed), 'chunked': chunked}), flush=True)
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


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else '/projection')
