"""Compare actual signal list rows in an isolated fixture; prints only counts."""
import os
import sqlite3
import uuid
from datetime import date,timedelta
from unittest.mock import patch
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from routers.spine_signals import _row_to_item, signals_summary as sqlite_summary, mention_momentum as sqlite_momentum
from pipeline.postgres_signals_fixture import signals_items, signals_summary as pg_summary, mention_momentum as pg_momentum
from pipeline.postgres_narrative_fixture import list_narratives as pg_narratives
from pipeline.narrative import list_narratives as sqlite_narratives
from routers.spine_narrative import NarrativeList


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
        latest=source.execute('SELECT max(date) FROM signals').fetchone()[0]
        if not latest: raise ValueError('No signal data')
        since=(date.fromisoformat(latest)-timedelta(days=7)).isoformat()
        signals=[dict(row) for row in source.execute('SELECT * FROM signals')]
        entities=[dict(row) for row in source.execute('SELECT * FROM entities')]
        narratives=[dict(row) for row in source.execute('SELECT * FROM narratives')]
        links=[dict(row) for row in source.execute("SELECT el.* FROM entity_links el JOIN raw_documents rd ON rd.id=el.doc_id WHERE el.link_type='stock' AND rd.published_at>=datetime('now','-14 days')")]
        documents=[dict(row) for row in source.execute("SELECT id,published_at FROM raw_documents WHERE published_at>=datetime('now','-14 days')")]
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('CREATE TABLE {}.legacy_snapshot_rows(table_name text,row_ordinal bigint,row_data jsonb)').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('CREATE TABLE {}.legacy_snapshot_tables(table_name text primary key)').format(sql.Identifier(schema)))
            conn.execute(sql.SQL("INSERT INTO {}.legacy_snapshot_tables VALUES ('signals')").format(sql.Identifier(schema)))
            conn.execute(sql.SQL("CREATE INDEX ON {}.legacy_snapshot_rows (table_name,(row_data->>'id'))").format(sql.Identifier(schema)))
            conn.execute(sql.SQL("CREATE INDEX ON {}.legacy_snapshot_rows (table_name,(row_data->>'signal_type'),(row_data->>'entity_id'))").format(sql.Identifier(schema)))
            with conn.cursor() as cur:
                for table,rows in [('entities',entities),('signals',signals),('narratives',narratives),('entity_links',links),('raw_documents',documents)]:
                    cur.executemany(sql.SQL('INSERT INTO {}.legacy_snapshot_rows VALUES (%s,%s,%s)').format(sql.Identifier(schema)),[(table,i,Jsonb(row)) for i,row in enumerate(rows)])
        counts=[]
        with psycopg.connect(dsn,options=f'-c search_path={schema}') as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            for kind in (None,'theme_surge','mention_surge'):
                where=['s.date >= ?']; params=[since]
                if kind:
                    where.append('s.signal_type = ?');params.append(kind)
                if kind == 'theme_surge':
                    where.append('s.date = (SELECT MAX(s2.date) FROM signals s2 WHERE s2.signal_type=s.signal_type AND s2.entity_id=s.entity_id)')
                rows=source.execute('SELECT s.*,e.name entity_name,e.aliases stock_code FROM signals s JOIN entities e ON e.id=s.entity_id WHERE '+ ' AND '.join(where)+' ORDER BY s.date DESC,s.id DESC',params)
                expected=[_row_to_item(row).model_dump() for row in rows]
                actual=[item.model_dump() for item in signals_items(conn,since=since,signal_type=kind)]
                if actual != expected: raise AssertionError('Signal list mismatch')
                counts.append(len(actual))
            def original_connection():
                connection=sqlite3.connect('file:/data/stock_explorer.db?mode=ro',uri=True)
                connection.row_factory=sqlite3.Row
                connection.execute('PRAGMA query_only=ON')
                return connection
            with patch('routers.spine_signals.get_connection',side_effect=original_connection):
                expected_summary=sqlite_summary(days=7).model_dump()
            if pg_summary(conn,days=7).model_dump() != expected_summary:
                raise AssertionError('Signal summary mismatch')
            with patch('routers.spine_signals.get_connection',side_effect=original_connection):
                expected_momentum=sqlite_momentum(limit=12).model_dump()['items']
            if pg_momentum(conn,limit=12).model_dump()['items'] != expected_momentum:
                raise AssertionError('Momentum mismatch')
            expected_narratives=NarrativeList(items=sqlite_narratives(source)).model_dump()
            actual_narratives=pg_narratives(conn).model_dump()
            if actual_narratives != expected_narratives:
                raise AssertionError('Narrative list mismatch')
        print(f'Compared signal lists {counts}, summary, {len(expected_momentum)} momentum and {len(expected_narratives["items"])} narratives: matched')
    finally:
        source.close()
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    main()
