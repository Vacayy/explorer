"""Recompute existing mention signals only inside a disposable PG snapshot."""
import sqlite3
import uuid
from psycopg.types.json import Jsonb
from pipeline.postgres_graph_fixture import _guard
from pipeline.signals import compute_mention_surge, compute_theme_surge


def compute_mention_signals(conn, *, as_of, include_themes=False):
    _guard(conn)
    names=('entities','raw_documents','entity_links','enrichments','signals')
    uri='file:fixture-'+uuid.uuid4().hex+'?mode=memory&cache=shared'
    root=sqlite3.connect(uri,uri=True)
    root.row_factory=sqlite3.Row
    try:
        fields={
            'entities':('id','type','name'),
            'raw_documents':('id','source_type','title','url','published_at'),
            'entity_links':('doc_id','entity_id','link_type'),
            'enrichments':('doc_id','time_orientation'),
        }
        for name in names:
            meta=conn.execute('SELECT columns,schema_sql FROM legacy_snapshot_tables WHERE table_name=%s',(name,)).fetchone()
            if not meta: raise ValueError('Required snapshot table missing: '+name)
            columns,ddl=meta
            if name in fields:
                columns=fields[name]
                if name == 'enrichments' and 'content_hash' in meta[0]:
                    columns=(*columns,'content_hash')
                ddl='CREATE TABLE "'+name+'" ('+','.join('"'+column+'"' for column in columns)+')'
            root.execute(ddl)
            quoted=','.join('"'+column.replace('"','""')+'"' for column in columns)
            placeholders=','.join('?' for _ in columns)
            if name == 'signals':
                rows=conn.execute('SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s ORDER BY row_ordinal',(name,))
                values=([row.get(column) for column in columns] for row, in rows)
            else:
                query='SELECT '+','.join("row_data->>'"+column+"'" for column in columns)+' FROM legacy_snapshot_rows WHERE table_name=%s ORDER BY row_ordinal'
                rows=conn.execute(query,(name,))
                numeric={'id','doc_id','entity_id'}
                values=([int(value) if column in numeric and value is not None else value
                         for column,value in zip(columns,row)] for row in rows)
            root.executemany(f'INSERT INTO "{name}" ({quoted}) VALUES ({placeholders})',values)
        # Match the source's index traversal for the original query, whose
        # representative document list has no explicit ORDER BY.
        root.execute('CREATE INDEX fixture_entity_type_name ON entities(type,name)')
        root.execute('CREATE INDEX fixture_link_entity_type ON entity_links(entity_id,link_type)')
        root.execute('CREATE INDEX fixture_link_doc_entity_type ON entity_links(doc_id,entity_id,link_type)')
        root.execute('CREATE INDEX fixture_document_id ON raw_documents(id)')
        enrichment_columns={row[1] for row in root.execute('PRAGMA table_info(enrichments)')}
        root.execute('CREATE INDEX fixture_enrichment_doc ON enrichments(doc_id'+(',content_hash' if 'content_hash' in enrichment_columns else '')+')')
        root.commit()
        def factory():
            db=sqlite3.connect(uri,uri=True)
            db.row_factory=sqlite3.Row
            return db
        generated=compute_mention_surge(as_of=as_of,connection_factory=factory)
        if include_themes:
            compute_theme_surge(connection_factory=factory)
        rows=[dict(row) for row in root.execute('SELECT * FROM signals')]
        conn.execute("DELETE FROM legacy_snapshot_rows WHERE table_name='signals'")
        with conn.cursor() as cursor:
            cursor.executemany("INSERT INTO legacy_snapshot_rows VALUES ('signals',%s,%s)",
                               [(i,Jsonb(row)) for i,row in enumerate(rows)])
        conn.execute("UPDATE legacy_snapshot_tables SET row_count=%s WHERE table_name='signals'",(len(rows),))
        return len(generated)
    finally:
        root.close()
