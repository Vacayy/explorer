"""Ordered one-time setup of the per-member ledgers on the candidate PG schema (public mode).

Each numbered step is idempotent (a present step is only recorded) and is recorded in `schema_migrations` once
applied. The public mode refuses to start while any step is pending (routers.postgres_public_assembly), so a
missed step can never surface as a 503 or a broken ownership split after exposure. Apply with
scripts/refactor_auth_initialize.py. The connection must be autocommit: each step's own transaction then
commits (inside an open implicit transaction it would only be a savepoint and roll back with it).
"""


def _table(name):
    return lambda conn: conn.execute('SELECT to_regclass(%s)', (name,)).fetchone()[0] is not None


def _column(table, column):
    return lambda conn: conn.execute('SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() '
                                     'AND table_name=%s AND column_name=%s', (table, column)).fetchone() is not None


def steps():
    """(version, name, present(conn), initialize(conn)) in application order."""
    from pipeline import postgres_identity_store, postgres_trial_quota, postgres_usage_gate
    from pipeline import postgres_client_errors, postgres_owner_legacy_fixture, postgres_study_owners
    from routers import postgres_member_thesis_fixture, postgres_questions_fixture
    return [
        (1, 'identity (principals, sessions)', _table('principals'), postgres_identity_store.initialize),
        (2, 'chat quota reservations', _table('chat_quota_reservations'), postgres_trial_quota.initialize),
        (3, 'anonymous compute rate limit', _table('anonymous_compute_requests'), postgres_usage_gate.initialize),
        (4, 'member questions', _table('question_principals'), postgres_questions_fixture.initialize_question_principals),
        (5, 'member question scenarios', _table('member_question_scenarios'), postgres_questions_fixture.initialize_member_scenarios),
        (6, 'member watch groups', _column('owner_legacy_rows', 'account_id'), postgres_owner_legacy_fixture.initialize_member_rows),
        (7, 'member studies', _table('study_principals'), postgres_study_owners.initialize),
        (8, 'member thesis audits', _table('member_thesis_audits'), postgres_member_thesis_fixture.initialize),
        (9, 'screen API error log', _table('client_errors'), postgres_client_errors.initialize),
    ]


def _recorded(conn):
    if conn.execute("SELECT to_regclass('schema_migrations')").fetchone()[0] is None:
        return set()
    return {row[0] for row in conn.execute('SELECT version FROM schema_migrations')}


def pending(conn):
    """Steps not both recorded and present, as (version, name)."""
    recorded = _recorded(conn)
    return [(version, name) for version, name, present, _ in steps() if version not in recorded or not present(conn)]


def apply(conn, *, report=print):
    """Apply every pending step in order and record it."""
    if not conn.autocommit:
        raise ValueError('An autocommit connection is required')
    conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY,name TEXT NOT NULL,'
                 'applied_at TIMESTAMPTZ NOT NULL DEFAULT now())')
    recorded = _recorded(conn)
    for version, name, present, initialize in steps():
        if not present(conn):
            initialize(conn)
            if not present(conn):
                raise RuntimeError(f'Migration {version} did not apply: {name}')
            report(f'applied  {version} {name}')
        else:
            report(f'present  {version} {name}')
        if version not in recorded:
            conn.execute('INSERT INTO schema_migrations(version,name) VALUES (%s,%s) ON CONFLICT DO NOTHING', (version, name))


class MigrationsPending(RuntimeError):
    """The public mode must not start before every per-member ledger exists."""


def require_applied(conn):
    missing = pending(conn)
    if missing:
        raise MigrationsPending('Public mode refused: pending migrations ' + ', '.join(f'{v} {n}' for v, n in missing))
