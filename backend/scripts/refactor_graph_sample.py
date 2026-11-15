"""Compare a few actual read-only transcript graphs with disposable PG rows."""
import os
import sqlite3
import uuid
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from pipeline.postgres_doc_graph_fixture import document_graph
from pipeline.postgres_transcript_fixture import transcript_detail,quarters
from routers.spine_transcript import _doc_graph,_detail_row,_build_detail,list_quarters
from unittest.mock import patch


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
    try:
        ids=[r[0] for r in source.execute("SELECT DISTINCT source_doc_id FROM entity_relations WHERE source_doc_id IS NOT NULL AND rel_type IN ('CAUSES','BENEFITS_FROM') LIMIT 5")]
        ids+= [r[0] for r in source.execute('SELECT DISTINCT doc_id FROM entity_links LIMIT 5') if r[0] not in ids]
        transcripts=[dict(r) for r in source.execute('SELECT * FROM transcripts WHERE raw_doc_id IS NOT NULL LIMIT 3')]
        ids+= [r['raw_doc_id'] for r in transcripts if r['raw_doc_id'] not in ids]
        if not ids:
            raise ValueError('No graph samples')
        marks=','.join('?' for _ in ids)
        links=[dict(r) for r in source.execute(f'SELECT * FROM entity_links WHERE doc_id IN ({marks})',ids)]
        edges=[dict(r) for r in source.execute(f'SELECT * FROM entity_relations WHERE source_doc_id IN ({marks})',ids)]
        entity_ids={r['entity_id'] for r in links}|{r[key] for r in edges for key in ('src_id','dst_id')}
        marks=','.join('?' for _ in entity_ids)
        entities=[dict(r) for r in source.execute(f'SELECT * FROM entities WHERE id IN ({marks})',list(entity_ids))] if entity_ids else []
        marks=','.join('?' for _ in transcripts)
        tickers=[row['ticker'] for row in transcripts]
        follows=[dict(r) for r in source.execute(f'SELECT * FROM transcript_follow WHERE ticker IN ({marks})',tickers)] if tickers else []
        doc_ids=[row['raw_doc_id'] for row in transcripts]
        docs=[dict(r) for r in source.execute(f'SELECT * FROM raw_documents WHERE id IN ({marks})',doc_ids)] if doc_ids else []
        all_quarters=[dict(r) for r in source.execute(f'SELECT * FROM transcripts WHERE ticker IN ({marks})',tickers)] if tickers else []
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('CREATE TABLE {}.legacy_snapshot_rows(table_name text,row_ordinal bigint,row_data jsonb)').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('CREATE TABLE {}.legacy_snapshot_tables(table_name text primary key)').format(sql.Identifier(schema)))
            with conn.cursor() as cur:
                for table, rows in [('entities',entities),('entity_links',links),('entity_relations',edges),('transcripts',all_quarters),('transcript_follow',follows),('raw_documents',docs)]:
                    cur.execute(sql.SQL('INSERT INTO {}.legacy_snapshot_tables VALUES (%s)').format(sql.Identifier(schema)),(table,))
                    cur.executemany(sql.SQL('INSERT INTO {}.legacy_snapshot_rows VALUES (%s,%s,%s)').format(sql.Identifier(schema)),[(table,i,Jsonb(row)) for i,row in enumerate(rows)])
        with psycopg.connect(dsn,options=f'-c search_path={schema}') as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            for ident in ids:
                if document_graph(conn,ident) != _doc_graph(source,ident):
                    raise AssertionError('Document graph mismatch')
            for row in transcripts:
                if transcript_detail(conn,row['id']).model_dump() != _build_detail(source,_detail_row(source,row['id'])).model_dump():
                    raise AssertionError('Transcript detail mismatch')
            class SourceWrapper:
                def execute(self,*args): return source.execute(*args)
                def close(self): pass
            for ticker in set(tickers):
                with patch('routers.spine_transcript.get_connection',side_effect=SourceWrapper):
                    expected=[item.model_dump() for item in list_quarters(ticker)]
                if [item.model_dump() for item in quarters(conn,ticker)] != expected:
                    raise AssertionError('Transcript quarter mismatch')
        print(f'Compared {len(ids)} document graphs, {len(transcripts)} transcript details and {len(set(tickers))} quarter lists: matched')
    finally:
        source.close()
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    main()
