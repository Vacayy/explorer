"""Run existing urgent selection against a disposable captured PG snapshot.

Selection only: no model, narrative generation, or source data write occurs.
"""
import sqlite3
import uuid

from pipeline.narrative import compute_urgent_narratives
from pipeline.postgres_graph_fixture import _guard

TABLES = ('entities','entity_links','raw_documents','enrichments','narratives',
          'signals','market_today','market_today_links','narrative_candidates')


def select_urgent(conn):
    _guard(conn)
    meta = {name:(columns,ddl) for name,columns,ddl in conn.execute(
        'SELECT table_name,columns,schema_sql FROM legacy_snapshot_tables WHERE table_name=ANY(%s)',(list(TABLES),))}
    if set(meta) != set(TABLES):
        raise ValueError('Complete narrative input snapshot required')
    uri='file:urgent-fixture-'+uuid.uuid4().hex+'?mode=memory&cache=shared'
    root=sqlite3.connect(uri,uri=True)
    root.row_factory=sqlite3.Row
    try:
        for name in TABLES:
            columns,ddl=meta[name]
            root.execute(ddl)
            actual=[row['name'] for row in root.execute('PRAGMA table_info("'+name+'")')]
            if actual != columns:
                raise ValueError('Narrative snapshot schema mismatch')
            quoted=','.join('"'+column.replace('"','""')+'"' for column in columns)
            placeholders=','.join('?' for _ in columns)
            rows=conn.execute('SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s ORDER BY row_ordinal',(name,))
            root.executemany('INSERT INTO "'+name+'" ('+quoted+') VALUES ('+placeholders+')',
                             (tuple(row[0].get(column) for column in columns) for row in rows))
        root.commit()
        def connect():
            db=sqlite3.connect(uri,uri=True)
            db.row_factory=sqlite3.Row
            return db
        return compute_urgent_narratives(connection_factory=connect,
            generate=lambda topic:{'status':'selected'},record_candidate=lambda topic,status:None)
    finally:
        root.close()
