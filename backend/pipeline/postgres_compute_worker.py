"""One compute-worker pass for the single-path preview, outside the API process.

A pass runs as a fresh process in its own container: reranker and embedding models are loaded
only when a retrieval job is queued, and released when the pass ends. A pass keeps taking jobs
until none has been queued for IDLE_SECONDS, so one AI answer's several evidence searches load
the models once. `--watch` is the container's long-lived loop: one query a second on a kept
connection, starting a pass only when a job is queued (a fresh interpreter each second cost
about 0.27 CPU seconds).
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
    from pipeline import llm, postgres_llm_calls
    postgres_llm_calls.install(llm, factory)  # this worker's model calls (chat tools, claims) too
    directory = Path(directory)
    manifest = json.loads((directory / 'current.json').read_text())
    from pipeline.postgres_claims_fixture import related_documents
    from pipeline.postgres_retrieval_jobs import chat_tool, legacy_retrieval, run_queued
    legacy_retrieval(directory / 'chunks.db', directory / manifest['file'])
    from pipeline.postgres_keyword_backfill import backfill
    projection_path = directory / manifest['file']
    handlers = {'doc_claims': related_documents, 'chat_tool': chat_tool,
                'keyword_backfill': lambda factory, request: backfill(factory, projection_path, request['keyword_id'])}
    last = time.monotonic()
    while time.monotonic() - last < IDLE_SECONDS:
        done = run_queued(factory, handlers)
        if done:
            print(json.dumps({'jobs': done}), flush=True)
            last = time.monotonic()
        else:
            time.sleep(.3)


def watch(interval=1.0):
    import subprocess
    import sys
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
    conn = None
    while True:
        try:
            if conn is None or conn.closed:
                conn = psycopg.connect(dsn, options=f'-c search_path={schema}', autocommit=True)
            queued = conn.execute("SELECT EXISTS(SELECT 1 FROM retrieval_jobs WHERE status='queued')").fetchone()[0]
        except psycopg.Error as exc:
            print(f'watch check failed: {type(exc).__name__}', flush=True)
            conn = None
            queued = False
        if queued:
            subprocess.run([sys.executable, '-m', 'pipeline.postgres_compute_worker'], check=False)
        else:
            time.sleep(interval)


if __name__ == '__main__':
    import sys
    watch() if sys.argv[1:] == ['--watch'] else main()
