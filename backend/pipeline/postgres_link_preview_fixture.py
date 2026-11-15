"""Run the existing SQLite linker against an isolated archived registry.

The result is a preview, not an applied enrichment. Any entity, keyword or
relation creation is rejected instead of silently dropping the side effect.
"""
import os
import re
import sqlite3
from pipeline.store import _link


def preview_links(conn, document_id, result):
    database,schema=conn.execute('SELECT current_database(),current_schema()').fetchone()
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or database != 'fixture' or
            not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',schema)):
        raise ValueError('Disposable fixture schema required')
    if (conn.execute('SHOW transaction_isolation').fetchone()[0] != 'repeatable read' or
            conn.execute('SHOW transaction_read_only').fetchone()[0] != 'on'):
        raise ValueError('A repeatable-read read-only transaction is required')
    required={'entities','entity_keywords','entity_relations'}
    present={r[0] for r in conn.execute('SELECT table_name FROM legacy_snapshot_tables WHERE table_name=ANY(%s)',(list(required),))}
    if present != required:
        raise ValueError('Complete linking registry snapshot required')
    doc=conn.execute('SELECT title,markdown,revision FROM ingest_documents WHERE id=%s',(document_id,)).fetchone()
    if doc is None:
        raise ValueError('Document not found')
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    try:
        db.executescript('''
          CREATE TABLE entities(id INTEGER PRIMARY KEY,type TEXT NOT NULL,name TEXT NOT NULL,UNIQUE(type,name));
          CREATE TABLE entity_keywords(entity_id INTEGER,keyword TEXT,status TEXT,UNIQUE(entity_id,keyword));
          CREATE TABLE entity_links(doc_id INTEGER,entity_id INTEGER,link_type TEXT,confidence REAL,UNIQUE(doc_id,entity_id,link_type));
          CREATE TABLE entity_relations(src_id INTEGER,dst_id INTEGER,rel_type TEXT,epistemic_type TEXT,
            confidence REAL,source_doc_id INTEGER,valid_from TEXT,UNIQUE(src_id,dst_id,rel_type,valid_from));
        ''')
        for (row,) in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entities' ORDER BY row_ordinal"):
            db.execute('INSERT INTO entities VALUES (?,?,?)',(row['id'],row['type'],row['name']))
        for (row,) in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entity_keywords' ORDER BY row_ordinal"):
            db.execute('INSERT INTO entity_keywords VALUES (?,?,?)',(row['entity_id'],row['keyword'],row.get('status')))
        for (row,) in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entity_relations' ORDER BY row_ordinal"):
            db.execute('INSERT INTO entity_relations VALUES (?,?,?,?,?,?,?)',(row['src_id'],row['dst_id'],row['rel_type'],
                       row.get('epistemic_type'),row.get('confidence'),row.get('source_doc_id'),row.get('valid_from')))
        before=tuple(db.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
                     for name in ('entities','entity_keywords','entity_relations'))
        _link(db,document_id,doc[0],doc[1],result)
        after=tuple(db.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
                    for name in ('entities','entity_keywords','entity_relations'))
        if before != after:
            raise ValueError('Unsupported entity, keyword or relation side effect')
        links=[dict(row) for row in db.execute('SELECT entity_id,link_type,confidence FROM entity_links ORDER BY rowid')]
        previous=conn.execute("SELECT count(*) FROM legacy_snapshot_rows WHERE table_name='entity_links' AND row_data->>'doc_id'=%s",(str(document_id),)).fetchone()[0]
        return {'revision':doc[2],'links':links,'legacy_links_replaced':previous}
    finally:
        db.close()
