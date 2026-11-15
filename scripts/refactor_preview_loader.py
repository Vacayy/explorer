"""Load one read-only rehearsal snapshot into a disposable local preview DB."""
import os
import re
import sqlite3
from datetime import datetime,timezone
from pathlib import Path
import psycopg
from psycopg import sql
from pipeline.postgres_snapshot import load_snapshot


def main():
    dsn=os.environ['REFACTOR_POSTGRES_DSN']
    schema=os.environ['REFACTOR_FIXTURE_SCHEMA']
    target=psycopg.conninfo.conninfo_to_dict(dsn)
    if (os.environ.get('REFACTOR_TEST_DISPOSABLE') != '1' or
        (target.get('host'),target.get('dbname'),target.get('user')) != ('pg','fixture','fixture') or
        not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',schema)):
        raise ValueError('Disposable local preview required')
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    def factory(): return psycopg.connect(dsn,options=f'-c search_path={schema}')
    with factory() as conn:
        conn.execute((Path(__file__).resolve().parents[1]/'backend/refactor_sql/document_projection.sql').read_text())
    source=sqlite3.connect('file:/data/stock_explorer.db?mode=ro',uri=True)
    source.row_factory=sqlite3.Row
    include_centroids=os.getenv('REFACTOR_INCLUDE_CENTROIDS') == '1'
    if include_centroids:
        import sqlite_vec
        source.enable_load_extension(True)
        try:
            sqlite_vec.load(source)
        finally:
            source.enable_load_extension(False)
    source.execute('PRAGMA query_only=ON')
    source.execute('BEGIN')
    try:
        result=load_snapshot(source,factory,snapshot_at=datetime.now(timezone.utc).isoformat(),
                             include_linking=True,include_signals=True,include_claims=True,
                             include_centroids=include_centroids)
        print('Preview snapshot loaded:',result,flush=True)
    finally:
        source.close()


if __name__ == '__main__': main()
