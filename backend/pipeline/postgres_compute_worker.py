"""One compute-worker pass for the single-path preview, outside the API process.

Runs as a fresh process every few seconds in its own container: reranker and embedding models
are loaded only when a retrieval job is queued, and released when the pass ends.
"""
import json
import os
from pathlib import Path

import psycopg


def main(directory='/projection'):
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
    factory = lambda: psycopg.connect(dsn, options=f'-c search_path={schema}', autocommit=True)
    with factory() as conn:
        if not conn.execute("SELECT EXISTS(SELECT 1 FROM retrieval_jobs WHERE status='queued')").fetchone()[0]:
            return
    directory = Path(directory)
    manifest = json.loads((directory / 'current.json').read_text())
    from pipeline.postgres_claims_fixture import related_documents
    from pipeline.postgres_retrieval_jobs import legacy_retrieval, run_queued
    legacy_retrieval(directory / 'chunks.db', directory / manifest['file'])
    print(json.dumps({'jobs': run_queued(factory, {'doc_claims': related_documents})}), flush=True)


if __name__ == '__main__':
    main()
