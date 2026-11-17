"""One-time setup of the per-member ledgers on the candidate PG schema (public mode).

  python scripts/refactor_auth_initialize.py           # report which steps are present (no change)
  python scripts/refactor_auth_initialize.py --apply   # run the missing ones, each committed on its own
Runs inside the backend environment (REFACTOR_POSTGRES_DSN, REFACTOR_FIXTURE_SCHEMA, REFACTOR_TEST_DISPOSABLE).
Every step is idempotent here: a present step is skipped. The connection is autocommit, so each initializer's
own transaction commits (inside an open implicit transaction it would only be a savepoint and roll back).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))
import psycopg  # noqa: E402


def _table(name):
    return lambda conn: conn.execute('SELECT to_regclass(%s)', (name,)).fetchone()[0] is not None


def _column(table, column):
    return lambda conn: conn.execute('SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() '
                                     'AND table_name=%s AND column_name=%s', (table, column)).fetchone() is not None


def steps():
    from pipeline import postgres_identity_store, postgres_trial_quota, postgres_usage_gate
    from pipeline import postgres_owner_legacy_fixture, postgres_study_owners
    from routers import postgres_member_thesis_fixture, postgres_questions_fixture
    return [
        ('identity (principals, sessions)', _table('principals'), postgres_identity_store.initialize),
        ('chat quota reservations', _table('chat_quota_reservations'), postgres_trial_quota.initialize),
        ('anonymous compute rate limit', _table('anonymous_compute_requests'), postgres_usage_gate.initialize),
        ('member questions', _table('question_principals'), postgres_questions_fixture.initialize_question_principals),
        ('member question scenarios', _table('member_question_scenarios'), postgres_questions_fixture.initialize_member_scenarios),
        ('member watch groups', _column('owner_legacy_rows', 'account_id'), postgres_owner_legacy_fixture.initialize_member_rows),
        ('member studies', _table('study_principals'), postgres_study_owners.initialize),
        ('member thesis audits', _table('member_thesis_audits'), postgres_member_thesis_fixture.initialize),
    ]


def main(apply):
    conn = psycopg.connect(os.environ['REFACTOR_POSTGRES_DSN'], autocommit=True,
                           options='-c search_path=' + os.environ['REFACTOR_FIXTURE_SCHEMA'])
    missing = 0
    for name, present, initialize in steps():
        if present(conn):
            print(f'present  {name}')
        elif apply:
            initialize(conn)
            print(f'created  {name}' if present(conn) else f'FAILED   {name}')
        else:
            missing += 1
            print(f'missing  {name}')
    if _table('principals')(conn):
        operators = conn.execute("SELECT count(*) FROM principals WHERE role='operator' AND enabled").fetchone()[0]
        print(f'operator principals: {operators} (remap the legacy owner with postgres_principals.remap_operator)')
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main('--apply' in sys.argv[1:]))
