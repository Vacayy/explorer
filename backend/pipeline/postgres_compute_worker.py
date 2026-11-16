"""One compute-worker pass for the single-path preview, outside the API process.

Runs as a fresh process every few seconds in its own container: reranker and embedding models
are loaded only when a retrieval job is queued, and released when the pass ends. A pass keeps
taking jobs until none has been queued for IDLE_SECONDS, so one AI answer's several evidence
searches load the models once.
"""
import json
import os
import time
from pathlib import Path

IDLE_SECONDS = float(os.environ.get('REFACTOR_WORKER_IDLE_SECONDS', '90'))

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
    from pipeline.postgres_retrieval_jobs import chat_search, legacy_retrieval, run_queued
    legacy_retrieval(directory / 'chunks.db', directory / manifest['file'])
    handlers = {'doc_claims': related_documents, 'chat_search': chat_search}
    last = time.monotonic()
    while time.monotonic() - last < IDLE_SECONDS:
        done = run_queued(factory, handlers)
        if done:
            print(json.dumps({'jobs': done}), flush=True)
            last = time.monotonic()
        else:
            time.sleep(.3)


if __name__ == '__main__':
    main()
