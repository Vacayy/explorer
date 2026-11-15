"""Transactional graph-side effects for the disposable ingestion experiment."""
import os
import re
import sqlite3
from pipeline.store import _link
from pipeline.postgres_ingest_fixture import finish_enrichment

GRAPH_LOCK=0x4558504C47524150


def _guard(conn):
    database,schema=conn.execute('SELECT current_database(),current_schema()').fetchone()
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or database != 'fixture' or
            not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',schema)):
        raise ValueError('Disposable fixture schema required')


def initialize_graph(conn):
    _guard(conn)
    if conn.execute('SHOW transaction_isolation').fetchone()[0] != 'read committed':
        raise ValueError('Graph writes require read committed isolation')
    conn.execute('SELECT pg_advisory_xact_lock(%s)',(GRAPH_LOCK,))
    if conn.execute('SELECT 1 FROM ingest_graph_state').fetchone():
        raise ValueError('Graph already initialized')
    required={'entities','entity_keywords','entity_relations'}
    present={r[0] for r in conn.execute('SELECT table_name FROM legacy_snapshot_tables WHERE table_name=ANY(%s)',(list(required),))}
    if present != required:
        raise ValueError('Complete linking registry snapshot required')
    for (row,) in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entities' ORDER BY row_ordinal"):
        conn.execute('INSERT INTO ingest_graph_entities(id,type,name,aliases,status,created_at) OVERRIDING SYSTEM VALUE VALUES (%s,%s,%s,%s,%s,%s)',
                     (row['id'],row['type'],row['name'],row.get('aliases'),row.get('status'),row.get('created_at')))
    for (row,) in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='entity_keywords' ORDER BY row_ordinal"):
        if row.get('id') is not None:
            conn.execute('INSERT INTO ingest_graph_keywords(id,entity_id,keyword,status,created_at) OVERRIDING SYSTEM VALUE VALUES (%s,%s,%s,%s,%s)',
                         (row['id'],row['entity_id'],row['keyword'],row.get('status'),row.get('created_at')))
        else:
            conn.execute('INSERT INTO ingest_graph_keywords(entity_id,keyword,status,created_at) VALUES (%s,%s,%s,%s)',
                         (row['entity_id'],row['keyword'],row.get('status'),row.get('created_at')))
    for ordinal,row in conn.execute("SELECT row_ordinal,row_data FROM legacy_snapshot_rows WHERE table_name='entity_relations' ORDER BY row_ordinal"):
        values=(row['src_id'],row['dst_id'],row['rel_type'],row.get('epistemic_type'),row.get('confidence'),
                row.get('source_doc_id'),row.get('valid_from'),ordinal)
        if row.get('id') is not None:
            conn.execute('INSERT INTO ingest_graph_relations(id,src_id,dst_id,rel_type,epistemic_type,confidence,source_doc_id,valid_from,source_ordinal) '
                         'OVERRIDING SYSTEM VALUE VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',(row['id'],*values))
        else:
            conn.execute('INSERT INTO ingest_graph_relations(src_id,dst_id,rel_type,epistemic_type,confidence,source_doc_id,valid_from,source_ordinal) '
                         'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',values)
    conn.execute("SELECT setval(pg_get_serial_sequence('ingest_graph_entities','id'), "
                 "GREATEST(COALESCE((SELECT max(id) FROM ingest_graph_entities),0),1), EXISTS(SELECT 1 FROM ingest_graph_entities))")
    conn.execute("SELECT setval(pg_get_serial_sequence('ingest_graph_keywords','id'), "
                 "GREATEST(COALESCE((SELECT max(id) FROM ingest_graph_keywords),0),1), EXISTS(SELECT 1 FROM ingest_graph_keywords))")
    conn.execute("SELECT setval(pg_get_serial_sequence('ingest_graph_relations','id'), "
                 "GREATEST(COALESCE((SELECT max(id) FROM ingest_graph_relations),0),1), EXISTS(SELECT 1 FROM ingest_graph_relations))")
    conn.execute('INSERT INTO ingest_graph_state DEFAULT VALUES')


def finish_with_graph(conn, document_id, *, revision, token, summary, model, result):
    """Run the existing linker; commit summary, graph side effects and links together."""
    _guard(conn)
    if conn.execute('SHOW transaction_isolation').fetchone()[0] != 'read committed':
        raise ValueError('Graph writes require read committed isolation')
    doc=conn.execute('SELECT title,markdown,revision FROM ingest_documents WHERE id=%s FOR UPDATE',(document_id,)).fetchone()
    job=conn.execute('SELECT revision,status,token FROM ingest_enrichment_jobs WHERE document_id=%s',(document_id,)).fetchone()
    if not doc or doc[2] != revision or job != (revision,'running',token):
        return False
    conn.execute('SELECT pg_advisory_xact_lock(%s)',(GRAPH_LOCK,))
    if not conn.execute('SELECT 1 FROM ingest_graph_state').fetchone():
        raise ValueError('Graph not initialized')
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    try:
        db.executescript('''CREATE TABLE entities(id INTEGER PRIMARY KEY,type TEXT NOT NULL,name TEXT NOT NULL,UNIQUE(type,name));
            CREATE TABLE entity_keywords(entity_id INTEGER,keyword TEXT,status TEXT,UNIQUE(entity_id,keyword));
            CREATE TABLE entity_links(doc_id INTEGER,entity_id INTEGER,link_type TEXT,confidence REAL,UNIQUE(doc_id,entity_id,link_type));
            CREATE TABLE entity_relations(src_id INTEGER,dst_id INTEGER,rel_type TEXT,epistemic_type TEXT,confidence REAL,source_doc_id INTEGER,valid_from TEXT,UNIQUE(src_id,dst_id,rel_type,valid_from));''')
        entities=conn.execute('SELECT id,type,name FROM ingest_graph_entities ORDER BY id').fetchall()
        keywords=conn.execute('SELECT entity_id,keyword,status FROM ingest_graph_keywords').fetchall()
        relations=conn.execute('SELECT src_id,dst_id,rel_type,epistemic_type,confidence,source_doc_id,valid_from FROM ingest_graph_relations ORDER BY id').fetchall()
        db.executemany('INSERT INTO entities VALUES (?,?,?)',entities)
        db.executemany('INSERT INTO entity_keywords VALUES (?,?,?)',keywords)
        db.executemany('INSERT INTO entity_relations VALUES (?,?,?,?,?,?,?)',relations)
        old_entities={r[0] for r in entities}; old_keywords={(r[0],r[1]) for r in keywords}
        last_relation=db.execute('SELECT COALESCE(max(rowid),0) FROM entity_relations').fetchone()[0]
        _link(db,document_id,doc[0],doc[1],result)
        remap={ident:ident for ident in old_entities}
        for row in db.execute('SELECT id,type,name FROM entities ORDER BY id'):
            if row['id'] not in old_entities:
                actual=conn.execute('INSERT INTO ingest_graph_entities(type,name,status) VALUES (%s,%s,%s) '
                                    'ON CONFLICT(type,name) DO UPDATE SET name=excluded.name RETURNING id',
                                    (row['type'],row['name'],'active')).fetchone()[0]
                remap[row['id']]=actual
        for row in db.execute('SELECT entity_id,keyword,status FROM entity_keywords ORDER BY rowid'):
            if (row['entity_id'],row['keyword']) not in old_keywords:
                conn.execute('INSERT INTO ingest_graph_keywords(entity_id,keyword,status) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                             (remap[row['entity_id']],row['keyword'],row['status']))
        for row in db.execute('SELECT src_id,dst_id,rel_type,epistemic_type,confidence,source_doc_id,valid_from FROM entity_relations WHERE rowid>? ORDER BY rowid',(last_relation,)):
            conn.execute('INSERT INTO ingest_graph_relations(src_id,dst_id,rel_type,epistemic_type,confidence,source_doc_id,valid_from) '
                         'VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         (remap[row['src_id']],remap[row['dst_id']],row['rel_type'],row['epistemic_type'],row['confidence'],row['source_doc_id'],row['valid_from']))
        links=list(db.execute('SELECT entity_id,link_type,confidence FROM entity_links ORDER BY rowid'))
        if not finish_enrichment(conn,document_id=document_id,revision=revision,token=token,summary=summary,model=model):
            raise RuntimeError('Claim changed during graph update')
        conn.execute('DELETE FROM ingest_entity_links WHERE document_id=%s',(document_id,))
        for position,row in enumerate(links):
            conn.execute('INSERT INTO ingest_entity_links VALUES (%s,%s,%s,%s,%s,%s)',
                         (document_id,revision,position,remap[row['entity_id']],row['link_type'],row['confidence']))
        conn.execute('UPDATE ingest_documents SET links_dirty=TRUE WHERE id=%s',(document_id,))
        return True
    finally:
        db.close()
