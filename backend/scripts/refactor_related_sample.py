"""Compare related-document reads on one read-only rehearsal snapshot."""
import os
import sqlite3
import time
import uuid
from unittest.mock import patch
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from pipeline.postgres_related_documents import CentroidIndex, related_documents
from pipeline.search import related_docs


def main():
    dsn=os.environ['REFACTOR_POSTGRES_DSN']
    target=psycopg.conninfo.conninfo_to_dict(dsn)
    if (os.environ.get('REFACTOR_TEST_DISPOSABLE'),target.get('host'),target.get('dbname'),target.get('user')) != ('1','pg','fixture','fixture'):
        raise ValueError('Disposable fixture required')
    schema='refactor_fixture_'+uuid.uuid4().hex
    source=sqlite3.connect('file:/data/stock_explorer.db?mode=ro',uri=True)
    source.row_factory=sqlite3.Row
    import sqlite_vec
    source.enable_load_extension(True);sqlite_vec.load(source);source.enable_load_extension(False)
    source.execute('PRAGMA query_only=ON');source.execute('BEGIN')
    generation=uuid.uuid4()
    fields={'raw_documents':('id','source_type','source_id','url','title','published_at'),
            'entities':('id','name','type','aliases'),
            'entity_links':('doc_id','entity_id','link_type','confidence')}
    try:
        ids=[]
        for row in source.execute('SELECT id FROM raw_documents ORDER BY published_at DESC LIMIT 100'):
            if source.execute('SELECT 1 FROM doc_centroid_vec WHERE rowid=?',(row['id'],)).fetchone():
                ids.append(row['id'])
            if len(ids)==3: break
        if len(ids)<3: raise ValueError('Insufficient vector samples')
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('CREATE TABLE {}.legacy_snapshot_rows(table_name text,row_ordinal bigint,row_data jsonb)').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('CREATE TABLE {}.snapshot_metadata(singleton boolean,generation_id uuid)').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('INSERT INTO {}.snapshot_metadata VALUES (true,%s)').format(sql.Identifier(schema)),(generation,))
            for key in ('id','doc_id','entity_id'):
                conn.execute(sql.SQL("CREATE INDEX ON {}.legacy_snapshot_rows (table_name,(row_data->>"+"'"+key+"'"+"))").format(sql.Identifier(schema)))
            for table in (*fields,'telegram_channels','blog_sources','youtube_channels','scrap_links'):
                columns=fields.get(table) or tuple(row['name'] for row in source.execute(f'PRAGMA table_info("{table}")'))
                quoted=','.join('"'+name+'"' for name in columns)
                with conn.cursor() as cur:
                    batch=[]
                    for ordinal,row in enumerate(source.execute(f'SELECT {quoted} FROM "{table}" NOT INDEXED')):
                        batch.append((table,ordinal,Jsonb(dict(row))))
                        if len(batch)==2000:
                            cur.executemany(sql.SQL('INSERT INTO {}.legacy_snapshot_rows VALUES (%s,%s,%s)').format(sql.Identifier(schema)),batch);batch=[]
                    if batch: cur.executemany(sql.SQL('INSERT INTO {}.legacy_snapshot_rows VALUES (%s,%s,%s)').format(sql.Identifier(schema)),batch)
        started=time.monotonic()
        index=CentroidIndex(generation,((row['rowid'],row['embedding']) for row in source.execute('SELECT rowid,embedding FROM doc_centroid_vec')))
        build=time.monotonic()-started
        class SourceWrapper:
            def execute(self,*args): return source.execute(*args)
            def close(self): pass
        old_times=[];new_times=[]
        try:
            with psycopg.connect(dsn,options=f'-c search_path={schema}') as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                for ident in ids:
                    started=time.monotonic()
                    with patch('pipeline.search._vec_conn',side_effect=SourceWrapper): expected=related_docs(ident)
                    old_times.append(time.monotonic()-started)
                    started=time.monotonic();actual=related_documents(conn,index,ident);new_times.append(time.monotonic()-started)
                    if actual != expected: raise AssertionError('Related document mismatch')
        finally:
            index.close()
        print(f'Matched {len(ids)} documents; index build {build:.2f}s; old query {sum(old_times)/len(old_times):.3f}s avg; new query {sum(new_times)/len(new_times):.3f}s avg')
    finally:
        source.close()
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__': main()
