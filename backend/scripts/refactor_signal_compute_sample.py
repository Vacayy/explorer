"""Measure isolated mention-signal recomputation on read-only snapshot data."""
import os
import json
import re
import resource
import sqlite3
import time
import uuid
from datetime import datetime,timezone
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from pipeline.postgres_signal_compute_fixture import compute_mention_signals
from pipeline.signals import compute_mention_surge, compute_theme_surge


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
            'entity_links':('doc_id','entity_id','link_type'),'enrichments':('doc_id','time_orientation','content_hash')}
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
                rows=source.execute(f'SELECT {quoted} FROM "{name}" NOT INDEXED')
                with conn.cursor() as cursor:
                    batch=[]
                    for i,row in enumerate(rows):
                        batch.append((name,i,Jsonb(dict(row))))
                        if len(batch)==2000:
                            cursor.executemany(sql.SQL('INSERT INTO {}.legacy_snapshot_rows VALUES (%s,%s,%s)').format(sql.Identifier(schema)),batch)
                            batch=[]
                    if batch:
                        cursor.executemany(sql.SQL('INSERT INTO {}.legacy_snapshot_rows VALUES (%s,%s,%s)').format(sql.Identifier(schema)),batch)
        as_of=datetime.now(timezone.utc)
        # main is opened mode=ro; only a temporary signals table is writable.
        source.execute('PRAGMA query_only=OFF')
        ddl=source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='signals'").fetchone()[0]
        temp_ddl,count=re.subn(r'^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?',
                                'CREATE TEMP TABLE ',ddl,count=1,flags=re.IGNORECASE)
        if count != 1: raise ValueError('Unsupported signals schema')
        source.execute(temp_ddl)
        source.execute('INSERT INTO temp.signals SELECT * FROM main.signals')
        class SourceWrapper:
            def execute(self,*args): return source.execute(*args)
            def commit(self): pass
            def close(self): pass
        expected=compute_mention_surge(as_of=as_of,connection_factory=SourceWrapper)
        expected_themes=compute_theme_surge(connection_factory=SourceWrapper)
        with psycopg.connect(dsn,options=f'-c search_path={schema}') as conn:
            started=time.monotonic()
            generated=compute_mention_signals(conn,as_of=as_of,include_themes=True)
            seconds=time.monotonic()-started
            peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
            actual={int(row['entity_id']):json.loads(row['payload_json']) for row, in conn.execute(
                "SELECT row_data FROM legacy_snapshot_rows WHERE table_name='signals' "
                "AND row_data->>'signal_type'='mention_surge' AND row_data->>'date'=%s",(as_of.date().isoformat(),))}
            mismatches=[row for row in expected if actual.get(row['entity_id']) != row['payload']]
            if generated != len(expected) or mismatches:
                fields={key for row in mismatches for key in row['payload'] if actual.get(row['entity_id'],{}).get(key) != row['payload'][key]}
                doc_sets=sum({d['id'] for d in actual.get(row['entity_id'],{}).get('docs',[])} != {d['id'] for d in row['payload']['docs']} for row in mismatches)
                raise AssertionError(f'Mention signal results differ: counts {generated}/{len(expected)}, mismatches {len(mismatches)}, fields {sorted(fields)}, different document sets {doc_sets}')
            actual_themes={int(row['entity_id']):json.loads(row['payload_json']) for row, in conn.execute(
                "SELECT row_data FROM legacy_snapshot_rows WHERE table_name='signals' "
                "AND row_data->>'signal_type'='theme_surge' AND row_data->>'date'=%s",(as_of.date().isoformat(),))}
            mismatched_themes=[row for row in expected_themes if actual_themes.get(row['entity_id']) != row['payload']]
            if mismatched_themes:
                fields={key for row in mismatched_themes for key in row['payload'] if actual_themes.get(row['entity_id'],{}).get(key) != row['payload'][key]}
                raise AssertionError(f'Theme signal mismatch: {len(mismatched_themes)} of {len(expected_themes)}; fields {sorted(fields)}')
        print(f'Computed and matched {generated} mention and {len(expected_themes)} theme signals in {seconds:.1f}s; process peak {peak:.0f} MiB (includes sample loading and original comparison)')
    finally:
        source.close()
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    main()
