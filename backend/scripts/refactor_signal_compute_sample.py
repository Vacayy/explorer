"""Measure isolated mention-signal recomputation on read-only snapshot data."""
import os
import resource
import sqlite3
import time
import uuid
from datetime import datetime,timezone
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from pipeline.postgres_signal_compute_fixture import compute_mention_signals


def main():
    dsn=os.environ['REFACTOR_POSTGRES_DSN']
    target=psycopg.conninfo.conninfo_to_dict(dsn)
    if (os.environ.get('REFACTOR_TEST_DISPOSABLE'),target.get('host'),target.get('dbname'),target.get('user')) != ('1','pg','fixture','fixture'):
        raise ValueError('Disposable fixture required')
    schema='refactor_fixture_'+uuid.uuid4().hex
    source=sqlite3.connect('file:/data/stock_explorer.db?mode=ro',uri=True)
    source.row_factory=sqlite3.Row
    source.execute('PRAGMA query_only=ON')
    source.execute('BEGIN')
    fields={'entities':('id','type','name'),'raw_documents':('id','source_type','title','url','published_at'),
            'entity_links':('doc_id','entity_id','link_type'),'enrichments':('doc_id','time_orientation')}
    try:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('CREATE TABLE {}.legacy_snapshot_tables(table_name text primary key,columns jsonb,schema_sql text,row_count bigint)').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('CREATE TABLE {}.legacy_snapshot_rows(table_name text,row_ordinal bigint,row_data jsonb,primary key(table_name,row_ordinal))').format(sql.Identifier(schema)))
            for name in (*fields,'signals'):
                info=source.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?',('table',name)).fetchone()
                if not info: raise ValueError('Source table missing')
                columns=fields.get(name) or tuple(row['name'] for row in source.execute(f'PRAGMA table_info("{name}")'))
                conn.execute(sql.SQL('INSERT INTO {}.legacy_snapshot_tables VALUES (%s,%s,%s,0)').format(sql.Identifier(schema)),(name,Jsonb(columns),info['sql']))
                quoted=','.join('"'+column.replace('"','""')+'"' for column in columns)
                rows=source.execute(f'SELECT {quoted} FROM "{name}"')
                with conn.cursor() as cursor:
                    batch=[]
                    for i,row in enumerate(rows):
                        batch.append((name,i,Jsonb(dict(row))))
                        if len(batch)==2000:
                            cursor.executemany(sql.SQL('INSERT INTO {}.legacy_snapshot_rows VALUES (%s,%s,%s)').format(sql.Identifier(schema)),batch)
                            batch=[]
                    if batch:
                        cursor.executemany(sql.SQL('INSERT INTO {}.legacy_snapshot_rows VALUES (%s,%s,%s)').format(sql.Identifier(schema)),batch)
        with psycopg.connect(dsn,options=f'-c search_path={schema}') as conn:
            started=time.monotonic()
            generated=compute_mention_signals(conn,as_of=datetime.now(timezone.utc))
            seconds=time.monotonic()-started
            peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
        print(f'Computed {generated} mention signals in {seconds:.1f}s; process peak {peak:.0f} MiB (includes sample loading)')
    finally:
        source.close()
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    main()
