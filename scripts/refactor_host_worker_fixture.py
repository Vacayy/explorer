"""One synthetic host-worker run against an explicitly disposable localhost PG.

This experiment always uses a fake model. It cannot start production workers.
"""
import argparse
import os
import re
from unittest.mock import patch

import psycopg
from psycopg.conninfo import conninfo_to_dict

from pipeline.llm import LLMResult
from pipeline.postgres_enrich_worker_fixture import enrich_document, existing_enricher

LOCK = 0x4558504C4359434C


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--document-id', type=int, required=True)
    args = parser.parse_args()
    dsn = os.environ.get('REFACTOR_POSTGRES_DSN', '')
    schema = os.environ.get('REFACTOR_FIXTURE_SCHEMA', '')
    target = conninfo_to_dict(dsn)
    if (os.environ.get('REFACTOR_TEST_DISPOSABLE') != '1' or
            target.get('host') != '127.0.0.1' or target.get('dbname') != 'fixture' or
            target.get('user') != 'fixture' or 'hostaddr' in target or 'service' in target or
            not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema) or args.document_id < 1):
        raise ValueError('Explicit disposable localhost fixture required')

    def factory():
        return psycopg.connect(dsn, options='-c search_path=' + schema)

    response = LLMResult(text='{"summary":"합성 호스트 요약"}', model='fixture',
                         engine='claude-code', usage={'input': 1, 'output': 1}, duration_ms=1)
    with factory() as lease:
        if not lease.execute('SELECT pg_try_advisory_lock(%s)', (LOCK,)).fetchone()[0]:
            raise RuntimeError('Fixture worker already running')
        try:
            with patch.dict(os.environ, {'ENRICH_ENGINE':'claude-code', 'LLM_FALLBACK_ENGINE':'none'}), \
                 patch('pipeline.llm._run_claude_code', return_value=response):
                applied = enrich_document(factory, args.document_id, enrich=existing_enricher(factory))
        finally:
            lease.execute('SELECT pg_advisory_unlock(%s)', (LOCK,))
    print('fixture host worker:', 'applied' if applied else 'not applied')


if __name__ == '__main__':
    main()
