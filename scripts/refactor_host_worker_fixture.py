"""One synthetic host-worker run against an explicitly disposable localhost PG.

The default uses a fake model. Actual calls require explicit fixture-only opt-in.
It cannot start production workers.
"""
import argparse
import os
import re
from contextlib import nullcontext
from shutil import which
from unittest.mock import patch

import psycopg
from psycopg.conninfo import conninfo_to_dict

from pipeline.llm import LLMResult
from pipeline.postgres_enrich_worker_fixture import enrich_document, existing_enricher, recover_cycle_attempts

LOCK = 0x4558504C4359434C


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--document-id', type=int, required=True)
    parser.add_argument('--actual-model', action='store_true')
    args = parser.parse_args()
    dsn = os.environ.get('REFACTOR_POSTGRES_DSN', '')
    schema = os.environ.get('REFACTOR_FIXTURE_SCHEMA', '')
    target = conninfo_to_dict(dsn)
    if (os.environ.get('REFACTOR_TEST_DISPOSABLE') != '1' or
            target.get('host') != '127.0.0.1' or target.get('dbname') != 'fixture' or
            target.get('user') != 'fixture' or 'hostaddr' in target or 'service' in target or
            not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema) or args.document_id < 1):
        raise ValueError('Explicit disposable localhost fixture required')
    if args.actual_model and (os.environ.get('FIXTURE_ALLOW_REAL_MODEL') != '1' or not which('claude')):
        raise ValueError('Actual fixture calls require explicit opt-in and Claude CLI')

    def factory():
        return psycopg.connect(dsn, options='-c search_path=' + schema)

    response = LLMResult(text='{"summary":"합성 호스트 요약"}', model='fixture',
                         engine='claude-code', usage={'input': 1, 'output': 1}, duration_ms=1)
    with factory() as lease:
        if not lease.execute('SELECT pg_try_advisory_lock(%s)', (LOCK,)).fetchone()[0]:
            raise RuntimeError('Fixture worker already running')
        try:
            with factory() as conn:
                recover_cycle_attempts(conn)
            model = nullcontext() if args.actual_model else patch('pipeline.llm._run_claude_code', return_value=response)
            with patch.dict(os.environ, {'ENRICH_ENGINE':'claude-code', 'LLM_FALLBACK_ENGINE':'none'}), model:
                applied = enrich_document(factory, args.document_id, enrich=existing_enricher(factory), worker_id='cycle:host-fixture')
        finally:
            lease.execute('SELECT pg_advisory_unlock(%s)', (LOCK,))
    print('fixture host worker:', 'applied' if applied else 'not applied')


if __name__ == '__main__':
    main()
