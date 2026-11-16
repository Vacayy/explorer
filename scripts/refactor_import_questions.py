"""Import a previously verified scoped SQLite snapshot into a disposable schema."""
import os
from pathlib import Path
import re
import sqlite3
import sys

import psycopg
from pipeline.postgres_questions_import_fixture import import_questions


def main():
    path = Path(sys.argv[1])
    schema = os.environ['REFACTOR_FIXTURE_SCHEMA']
    dsn = os.environ['REFACTOR_POSTGRES_DSN']
    params = psycopg.conninfo.conninfo_to_dict(dsn)
    if (not path.is_absolute() or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema) or
            (params.get('host'), params.get('dbname'), params.get('user')) != ('pg', 'fixture', 'fixture')):
        raise ValueError('Only isolated disposable fixtures are allowed')
    source = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        if source.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Snapshot integrity check failed')
        with psycopg.connect(dsn, options=f'-c search_path={schema}') as target:
            print('Imported scoped question snapshot:', import_questions(source, target))
    finally:
        source.close()


if __name__ == '__main__':
    main()
