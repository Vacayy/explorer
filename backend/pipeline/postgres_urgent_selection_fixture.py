"""Run existing urgent selection against a disposable captured PG snapshot.

Selection only: no model, narrative generation, or source data write occurs.
"""
import sqlite3
import uuid

from pipeline.narrative import compute_urgent_narratives
from pipeline.postgres_graph_fixture import _guard

TABLES = ('entities','entity_links','raw_documents','enrichments','narratives',
          'signals','market_today','market_today_links','narrative_candidates')


def open_snapshot(conn, tables, *, document_ids=None):
    _guard(conn)
    meta = {name:(columns,ddl) for name,columns,ddl in conn.execute(
        'SELECT table_name,columns,schema_sql FROM legacy_snapshot_tables WHERE table_name=ANY(%s)',(list(tables),))}
    if set(meta) != set(tables):
        raise ValueError('Complete narrative input snapshot required')
    uri='file:urgent-fixture-'+uuid.uuid4().hex+'?mode=memory&cache=shared'
    root=sqlite3.connect(uri,uri=True)
    root.row_factory=sqlite3.Row
    try:
        for name in tables:
            columns,ddl=meta[name]
            root.execute(ddl)
            actual=[row['name'] for row in root.execute('PRAGMA table_info("'+name+'")')]
            if actual != columns:
                raise ValueError('Narrative snapshot schema mismatch')
            quoted=','.join('"'+column.replace('"','""')+'"' for column in columns)
            placeholders=','.join('?' for _ in columns)
            if name=='raw_documents' and document_ids is not None:
                rows=conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s AND row_data->>'id'=ANY(%s) ORDER BY row_ordinal",
                                  (name,[str(ident) for ident in document_ids]))
            else:
                rows=conn.execute('SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s ORDER BY row_ordinal',(name,))
            root.executemany('INSERT INTO "'+name+'" ('+quoted+') VALUES ('+placeholders+')',
                             (tuple(row[0].get(column) for column in columns) for row in rows))
        root.commit()
        return root,uri,meta
    except BaseException:
        root.close()
        raise


def select_urgent(conn):
    root,uri,_=open_snapshot(conn,TABLES)
    try:
        def connect():
            db=sqlite3.connect(uri,uri=True)
            db.row_factory=sqlite3.Row
            return db
        return compute_urgent_narratives(connection_factory=connect,
            generate=lambda topic:{'status':'selected'},record_candidate=lambda topic,status:None)
    finally:
        root.close()
