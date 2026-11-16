"""Apply the existing narrative writer to a disposable staging snapshot only.

The caller supplies a fake model result and owns the PostgreSQL transaction.
This is not a durable writer or an external model invocation.
"""
from psycopg.types.json import Jsonb

from pipeline.narrative import _build_prompt, _hash, _latest_narrative, _node_vocab, _persist_narrative, _resolve, gather
from pipeline.knowledge_recall import recall_for_query
from pipeline.postgres_urgent_selection_fixture import open_snapshot

TABLES=('entities','entity_links','raw_documents','enrichments','narratives',
        'entity_relations','narrative_edge_evidence','entity_merges')
CHANGED=('entities','entity_relations','narratives','narrative_edge_evidence')


def prepare_fixture_narrative(conn, topic, *, embedder, force=False):
    """Build the legacy prompt from a captured fixture; never call a model."""
    if not callable(embedder):
        raise ValueError('An explicit fixture embedder is required')
    if conn.execute('SHOW transaction_isolation').fetchone()[0] != 'repeatable read':
        raise ValueError('Repeatable-read transaction required')
    db,_,_=open_snapshot(conn,TABLES + ('knowledge','knowledge_evidence'))
    try:
        entity=_resolve(db,topic)
        if entity is None:
            return {'status':'not_found'}
        docs=gather(db,entity['id'])
        if len(docs)<3:
            return {'status':'empty'}
        previous=_latest_narrative(db,topic)
        digest=_hash(docs)
        if previous and previous['doc_ids_hash']==digest and not force:
            return {'status':'cached'}
        knowledge=recall_for_query(db,topic,embedder=embedder)
        return {'status':'ready','prompt':_build_prompt(topic,docs,knowledge,_node_vocab(db),previous),
                'doc_ids':[doc['id'] for doc in docs], 'knowledge_ids':[item['id'] for item in knowledge]}
    finally:
        db.close()


def persist_fixture_narrative(conn, topic, data, *, force=False):
    if conn.execute("SELECT to_regclass('ingest_documents')").fetchone()[0] is not None:
        raise ValueError('A separate staging snapshot is required')
    if conn.execute('SHOW transaction_isolation').fetchone()[0] != 'repeatable read':
        raise ValueError('Repeatable-read transaction required')
    if not isinstance(data,dict) or not all(isinstance(data.get(k),str) and data[k].strip() for k in ('title','narrative')):
        raise ValueError('A complete synthetic narrative is required')
    db,_,_=open_snapshot(conn,TABLES)
    try:
        entity=_resolve(db,topic)
        if entity is None:
            return {'status':'not_found'}
        docs=gather(db,entity['id'])
        if len(docs)<3:
            return {'status':'empty'}
        digest=_hash(docs)
        previous=_latest_narrative(db,topic)
        if previous and previous['doc_ids_hash']==digest and not force:
            return {'status':'cached'}
        ident,version,edges=_persist_narrative(db,topic,data,docs,digest)
        db.commit()
        for name in CHANGED:
            conn.execute('DELETE FROM legacy_snapshot_rows WHERE table_name=%s',(name,))
            rows=db.execute('SELECT * FROM "'+name+'" ORDER BY rowid')
            with conn.cursor() as cursor:
                cursor.executemany('INSERT INTO legacy_snapshot_rows VALUES (%s,%s,%s)',
                                   ((name,index,Jsonb(dict(row))) for index,row in enumerate(rows)))
            conn.execute('UPDATE legacy_snapshot_tables SET row_count=(SELECT count(*) FROM legacy_snapshot_rows WHERE table_name=%s) WHERE table_name=%s',(name,name))
        return {'status':'fresh','id':ident,'version':version,'edges':edges}
    finally:
        db.close()
