"""One compute-worker pass for the single-path preview, outside the API process.

Runs as a fresh process every few seconds in its own container (reranker and embedding models are
loaded only when there is work, and released when the pass ends). Today: related documents for
staged document claims.
"""
import json
import os
from pathlib import Path

import psycopg


def main(directory='/projection'):
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
    factory = lambda: psycopg.connect(dsn, options=f'-c search_path={schema}', autocommit=True)
    with factory() as conn:
        if not conn.execute("SELECT EXISTS(SELECT 1 FROM computed_doc_claims WHERE status='staged')").fetchone()[0]:
            return
    directory = Path(directory)
    manifest = json.loads((directory / 'current.json').read_text())
    from pipeline.postgres_claims_fixture import run_staged
    print(json.dumps({'claims': run_staged(factory, directory / 'chunks.db', directory / manifest['file'])}), flush=True)


if __name__ == '__main__':
    main()
