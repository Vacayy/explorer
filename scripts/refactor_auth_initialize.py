"""Apply the ordered per-member setup on the candidate PG schema (pipeline.postgres_schema_migrations).

  python scripts/refactor_auth_initialize.py           # report pending steps (no change); exit 1 if any
  python scripts/refactor_auth_initialize.py --apply   # apply and record every pending step, in order
Runs inside the backend environment (REFACTOR_POSTGRES_DSN, REFACTOR_FIXTURE_SCHEMA, REFACTOR_TEST_DISPOSABLE).
The public mode refuses to start until nothing is pending.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))
import psycopg  # noqa: E402
from pipeline import postgres_schema_migrations as migrations  # noqa: E402


def main(apply):
    conn = psycopg.connect(os.environ['REFACTOR_POSTGRES_DSN'], autocommit=True,
                           options='-c search_path=' + os.environ['REFACTOR_FIXTURE_SCHEMA'])
    if apply:
        migrations.apply(conn)
    missing = migrations.pending(conn)
    for version, name in missing:
        print(f'pending  {version} {name}')
    if not missing:
        print('all migrations applied')
    if conn.execute("SELECT to_regclass('principals')").fetchone()[0] is not None:
        operators = conn.execute("SELECT count(*) FROM principals WHERE role='operator' AND enabled").fetchone()[0]
        print(f'operator principals: {operators} (remap the legacy owner with postgres_principals.remap_operator)')
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main('--apply' in sys.argv[1:]))
