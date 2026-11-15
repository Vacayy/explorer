"""Compare actual signal list rows in an isolated fixture; prints only counts."""
import os
import sqlite3
import uuid
from datetime import date,timedelta
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from routers.spine_signals import _row_to_item
from pipeline.postgres_signals_fixture import signals_items


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
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('CREATE TABLE {}.legacy_snapshot_rows(table_name text,row_ordinal bigint,row_data jsonb)').format(sql.Identifier(schema)))
            conn.execute(sql.SQL("CREATE INDEX ON {}.legacy_snapshot_rows (table_name,(row_data->>'id'))").format(sql.Identifier(schema)))
            conn.execute(sql.SQL("CREATE INDEX ON {}.legacy_snapshot_rows (table_name,(row_data->>'signal_type'),(row_data->>'entity_id'))").format(sql.Identifier(schema)))
            with conn.cursor() as cur:
                for table,rows in [('entities',entities),('signals',signals)]:
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
        print(f'Compared signal lists all/theme/mentions: {counts}; matched')
    finally:
        source.close()
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    main()
