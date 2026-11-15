"""Recompute existing mention signals only inside a disposable PG snapshot."""
import sqlite3
import uuid
from psycopg.types.json import Jsonb
from pipeline.postgres_graph_fixture import _guard
from pipeline.signals import compute_mention_surge


def compute_mention_signals(conn, *, as_of):
    _guard(conn)
    names=('entities','raw_documents','entity_links','enrichments','signals')
    uri='file:fixture-'+uuid.uuid4().hex+'?mode=memory&cache=shared'
    root=sqlite3.connect(uri,uri=True)
    root.row_factory=sqlite3.Row
    try:
        for name in names:
            meta=conn.execute('SELECT columns,schema_sql FROM legacy_snapshot_tables WHERE table_name=%s',(name,)).fetchone()
            if not meta: raise ValueError('Required snapshot table missing: '+name)
            columns,ddl=meta
            root.execute(ddl)
            quoted=','.join('"'+column.replace('"','""')+'"' for column in columns)
            placeholders=','.join('?' for _ in columns)
            rows=conn.execute('SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s ORDER BY row_ordinal',(name,))
            root.executemany(f'INSERT INTO "{name}" ({quoted}) VALUES ({placeholders})',
                             ([row.get(column) for column in columns] for row, in rows))
        root.commit()
        def factory():
            db=sqlite3.connect(uri,uri=True)
            db.row_factory=sqlite3.Row
            return db
        generated=compute_mention_surge(as_of=as_of,connection_factory=factory)
        rows=[dict(row) for row in root.execute('SELECT * FROM signals')]
        conn.execute("DELETE FROM legacy_snapshot_rows WHERE table_name='signals'")
        with conn.cursor() as cursor:
            cursor.executemany("INSERT INTO legacy_snapshot_rows VALUES ('signals',%s,%s)",
                               [(i,Jsonb(row)) for i,row in enumerate(rows)])
        conn.execute("UPDATE legacy_snapshot_tables SET row_count=%s WHERE table_name='signals'",(len(rows),))
        return len(generated)
    finally:
        root.close()
