"""Disposable narrative ledger and stale-input claims. Caller owns transactions."""
from hashlib import sha256
from uuid import uuid4
import re
from psycopg import sql
from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import GRAPH_LOCK, _guard


def initialize_narrative_ledger(conn):
    _guard(conn)
    if conn.execute('SHOW transaction_isolation').fetchone()[0] != 'read committed':
        raise ValueError('Read committed isolation required')
    conn.execute('SELECT pg_advisory_xact_lock(%s)',(GRAPH_LOCK,))
    if not conn.execute('SELECT 1 FROM ingest_graph_state').fetchone():
        raise ValueError('Graph must be initialized first')
    if conn.execute('SELECT 1 FROM ingest_narrative_ledger_state').fetchone():
        raise ValueError('Narrative ledger already initialized')
    required={'narratives','narrative_edge_evidence'}
    present={row[0] for row in conn.execute('SELECT table_name FROM legacy_snapshot_tables WHERE table_name=ANY(%s)',(list(required),))}
    if present != required:
        raise ValueError('Narrative and evidence snapshots required')
    for (row,) in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='narratives' ORDER BY row_ordinal"):
        conn.execute('INSERT INTO ingest_narrative_versions(id,topic,version,source_row) OVERRIDING SYSTEM VALUE VALUES (%s,%s,%s,%s)',
                     (row['id'],row['topic'],row['version'],Jsonb(row)))
    for (row,) in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='narrative_edge_evidence' ORDER BY row_ordinal"):
        conn.execute('INSERT INTO ingest_narrative_evidence(id,source_row) OVERRIDING SYSTEM VALUE VALUES (%s,%s)',(row['id'],Jsonb(row)))
    for table in ('ingest_narrative_versions','ingest_narrative_evidence'):
        conn.execute("SELECT setval(pg_get_serial_sequence(%s,'id'), GREATEST(COALESCE((SELECT max(id) FROM " + table + "),0),1), EXISTS(SELECT 1 FROM " + table + "))",(table,))
    conn.execute('INSERT INTO ingest_narrative_ledger_state DEFAULT VALUES')


def _fingerprint(conn):
    parts=[]
    queries=(
        'SELECT id,revision,projection_version FROM ingest_documents',
        'SELECT id,type,name,aliases,status,source_row FROM ingest_graph_entities',
        'SELECT id,src_id,dst_id,rel_type,confidence,source_row FROM ingest_graph_relations',
    )
    for query in queries:
        value=conn.execute("SELECT md5(COALESCE(string_agg(to_jsonb(t)::text,'' ORDER BY t.id),'')) FROM ("+query+") t").fetchone()[0]
        parts.append(value)
    # Include the entire candidate set and evidence, including new candidates
    # that could change the top-four selection after an external call starts.
    value=conn.execute("SELECT md5(COALESCE(string_agg(table_name || ':' || row_ordinal::text || ':' || row_data::text, '' "
                       "ORDER BY table_name,row_ordinal),'')) FROM legacy_snapshot_rows "
                       "WHERE table_name IN ('knowledge','knowledge_evidence')").fetchone()[0]
    parts.append(value)
    return sha256('|'.join(parts).encode()).hexdigest()


def claim_narrative(conn, topic):
    _guard(conn)
    if not isinstance(topic,str) or not topic.strip():
        raise ValueError('Topic is required')
    conn.execute('SELECT pg_advisory_xact_lock(%s)',(GRAPH_LOCK,))
    if not conn.execute('SELECT 1 FROM ingest_narrative_ledger_state').fetchone():
        raise ValueError('Narrative ledger not initialized')
    existing=conn.execute('SELECT status FROM ingest_narrative_claims WHERE topic=%s FOR UPDATE',(topic,)).fetchone()
    if existing and existing[0] in ('claimed','unknown'):
        return None
    version=conn.execute('SELECT COALESCE(max(version),0) FROM ingest_narrative_versions WHERE topic=%s',(topic,)).fetchone()[0]
    token=uuid4()
    conn.execute("INSERT INTO ingest_narrative_claims VALUES (%s,%s,%s,%s,'claimed') "
                 "ON CONFLICT(topic) DO UPDATE SET token=excluded.token,base_version=excluded.base_version, "
                 "input_fingerprint=excluded.input_fingerprint,status='claimed'",(topic,token,version,_fingerprint(conn)))
    return token


def validate_narrative_claim(conn, topic, token):
    _guard(conn)
    conn.execute('SELECT pg_advisory_xact_lock(%s)',(GRAPH_LOCK,))
    claim=conn.execute('SELECT base_version,input_fingerprint,status,token FROM ingest_narrative_claims WHERE topic=%s FOR UPDATE',(topic,)).fetchone()
    if not claim or claim[2]!='claimed' or claim[3]!=token:
        return False
    version=conn.execute('SELECT COALESCE(max(version),0) FROM ingest_narrative_versions WHERE topic=%s',(topic,)).fetchone()[0]
    if version != claim[0] or _fingerprint(conn) != claim[1]:
        conn.execute("UPDATE ingest_narrative_claims SET status='stale' WHERE topic=%s",(topic,))
        return False
    return True


def commit_staged_narrative(conn, topic, token, stage_schema):
    """Merge one synthetic staged narrative and its graph changes atomically."""
    _guard(conn)
    if conn.execute('SHOW transaction_isolation').fetchone()[0] != 'read committed':
        raise ValueError('Read committed isolation required')
    if not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',stage_schema or ''):
        raise ValueError('Separate fixture staging schema required')
    if conn.execute('SELECT current_schema()').fetchone()[0] == stage_schema:
        raise ValueError('Source and staging schemas must differ')
    # Acquire the document table before graph lock: graph writers may first
    # acquire a document row, then the graph lock.
    conn.execute('LOCK TABLE legacy_snapshot_rows IN SHARE MODE')
    conn.execute('LOCK TABLE ingest_documents IN SHARE MODE')
    if not validate_narrative_claim(conn,topic,token):
        return False
    rows=sql.SQL('{}.legacy_snapshot_rows').format(sql.Identifier(stage_schema))
    metadata=sql.SQL('{}.legacy_snapshot_tables').format(sql.Identifier(stage_schema))
    required=['knowledge','knowledge_evidence']
    for table in (sql.SQL('legacy_snapshot_tables'),metadata):
        if conn.execute(sql.SQL('SELECT count(*) FROM {} WHERE table_name=ANY(%s)').format(table),(required,)).fetchone()[0] != 2:
            raise ValueError('Knowledge and evidence snapshots are required')
    for name in ('knowledge','knowledge_evidence'):
        mismatch=conn.execute(sql.SQL('SELECT EXISTS ((SELECT row_ordinal,row_data FROM legacy_snapshot_rows WHERE table_name=%s '
            'EXCEPT SELECT row_ordinal,row_data FROM {} WHERE table_name=%s) UNION ALL '
            '(SELECT row_ordinal,row_data FROM {} WHERE table_name=%s EXCEPT '
            'SELECT row_ordinal,row_data FROM legacy_snapshot_rows WHERE table_name=%s))').format(rows,rows),
            (name,name,name,name)).fetchone()[0]
        if mismatch:
            raise ValueError('Staging knowledge does not match the current ledger')
    mismatch=conn.execute(sql.SQL("SELECT count(*) FROM ingest_documents d FULL JOIN "
        "(SELECT row_data FROM {} WHERE table_name='raw_documents') r "
        "ON d.id::text=r.row_data->>'id' WHERE d.id IS NULL OR r.row_data IS NULL OR "
        "COALESCE(d.content_hash,'') IS DISTINCT FROM COALESCE(r.row_data->>'content_hash','')").format(rows)).fetchone()[0]
    if mismatch:
        raise ValueError('Staging documents do not match the current ledger')
    mismatch=conn.execute(sql.SQL("SELECT count(*) FROM ingest_enrichments e WHERE NOT EXISTS "
        "(SELECT 1 FROM {} r WHERE r.table_name='enrichments' AND r.row_data->>'doc_id'=e.document_id::text "
        "AND r.row_data->>'summary' IS NOT DISTINCT FROM e.summary AND r.row_data->>'model' IS NOT DISTINCT FROM e.model)").format(rows)).fetchone()[0]
    if mismatch:
        raise ValueError('Staging summaries do not match the current ledger')
    mismatch=conn.execute(sql.SQL("SELECT count(*) FROM ingest_graph_entities g LEFT JOIN "
        "(SELECT row_data FROM {} WHERE table_name='entities') r ON r.row_data->>'id'=g.id::text "
        "WHERE r.row_data IS NULL OR r.row_data->>'type' IS DISTINCT FROM g.type OR r.row_data->>'name' IS DISTINCT FROM g.name").format(rows)).fetchone()[0]
    if mismatch:
        raise ValueError('Staging entities do not match the current ledger')
    mismatch=conn.execute(sql.SQL("SELECT count(*) FROM ingest_graph_relations g LEFT JOIN "
        "(SELECT row_data FROM {} WHERE table_name='entity_relations') r ON r.row_data->>'id'=g.id::text "
        "WHERE r.row_data IS NULL OR r.row_data->>'src_id' IS DISTINCT FROM g.src_id::text "
        "OR r.row_data->>'dst_id' IS DISTINCT FROM g.dst_id::text OR r.row_data->>'rel_type' IS DISTINCT FROM g.rel_type").format(rows)).fetchone()[0]
    if mismatch:
        raise ValueError('Staging relations do not match the current ledger')
    base=conn.execute('SELECT base_version FROM ingest_narrative_claims WHERE topic=%s',(topic,)).fetchone()[0]
    staged=conn.execute(sql.SQL("SELECT row_data FROM {} WHERE table_name='narratives' AND row_data->>'topic'=%s "
        "ORDER BY (row_data->>'version')::integer DESC LIMIT 1").format(rows),(topic,)).fetchone()
    if not staged or int(staged[0]['version']) != base+1:
        raise ValueError('Staging narrative version does not follow the claim')
    narrative=dict(staged[0]); scratch_narrative=narrative['id']
    if base:
        previous=conn.execute('SELECT id,source_row FROM ingest_narrative_versions WHERE topic=%s AND version=%s FOR UPDATE',(topic,base)).fetchone()
        staged_previous=conn.execute(sql.SQL("SELECT row_data FROM {} WHERE table_name='narratives' AND row_data->>'id'=%s").format(rows),(str(previous[0]),)).fetchone()
        if not staged_previous or not staged_previous[0].get('superseded_at'):
            raise ValueError('Previous narrative version was not superseded')
        old=dict(previous[1]); old['superseded_at']=staged_previous[0]['superseded_at']
        conn.execute('UPDATE ingest_narrative_versions SET source_row=%s WHERE id=%s',(Jsonb(old),previous[0]))
    ident=conn.execute("INSERT INTO ingest_narrative_versions(topic,version,source_row) VALUES (%s,%s,'{}') RETURNING id",(topic,base+1)).fetchone()[0]
    narrative['id']=ident
    conn.execute('UPDATE ingest_narrative_versions SET source_row=%s WHERE id=%s',(Jsonb(narrative),ident))
    staged_entities={int(row['id']):row for (row,) in conn.execute(sql.SQL("SELECT row_data FROM {} WHERE table_name='entities'").format(rows))}
    touched=[row for (row,) in conn.execute(sql.SQL("SELECT row_data FROM {} WHERE table_name='entity_relations' AND row_data->>'narrative_id'=%s ORDER BY row_ordinal").format(rows),(str(scratch_narrative),))]
    entity_map={}
    def entity_id(scratch):
        scratch=int(scratch)
        if scratch in entity_map: return entity_map[scratch]
        row=dict(staged_entities[scratch])
        current=conn.execute('SELECT id,source_row FROM ingest_graph_entities WHERE type=%s AND name=%s',(row['type'],row['name'])).fetchone()
        if current:
            actual,original=current
            if row.get('meta_json') is not None:
                value=dict(original or row); value['id']=actual; value['meta_json']=row['meta_json']
                conn.execute('UPDATE ingest_graph_entities SET source_row=%s WHERE id=%s',(Jsonb(value),actual))
        else:
            actual=conn.execute('INSERT INTO ingest_graph_entities(type,name,aliases,status) VALUES (%s,%s,%s,%s) RETURNING id',
                                (row['type'],row['name'],row.get('aliases'),row.get('status'))).fetchone()[0]
            row['id']=actual
            conn.execute('UPDATE ingest_graph_entities SET source_row=%s WHERE id=%s',(Jsonb(row),actual))
        entity_map[scratch]=actual
        return actual
    relation_map={}
    fields=('confidence','narrative_id','mechanism','geo_scope','effect_strength','effect_direction','source_doc_id','source_quote','source_status')
    for raw in touched:
        row=dict(raw); scratch=int(row['id'])
        row['src_id'],row['dst_id']=entity_id(row['src_id']),entity_id(row['dst_id'])
        row['narrative_id']=ident
        current=conn.execute('SELECT id,source_row FROM ingest_graph_relations WHERE src_id=%s AND dst_id=%s AND rel_type=%s ORDER BY id LIMIT 1',
                             (row['src_id'],row['dst_id'],row['rel_type'])).fetchone()
        if current:
            actual,original=current
            value=dict(original or row)
            for field in fields:
                if field in row: value[field]=row[field]
            value['id']=actual
            conn.execute('UPDATE ingest_graph_relations SET confidence=%s,source_doc_id=%s,source_row=%s WHERE id=%s',
                         (row.get('confidence'),row.get('source_doc_id'),Jsonb(value),actual))
        else:
            actual=conn.execute('INSERT INTO ingest_graph_relations(src_id,dst_id,rel_type,epistemic_type,confidence,source_doc_id,valid_from) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id',(row['src_id'],row['dst_id'],row['rel_type'],row.get('epistemic_type'),row.get('confidence'),row.get('source_doc_id'),row.get('valid_from'))).fetchone()[0]
            row['id']=actual
            conn.execute('UPDATE ingest_graph_relations SET source_row=%s WHERE id=%s',(Jsonb(row),actual))
        relation_map[scratch]=actual
    evidence=conn.execute(sql.SQL("SELECT row_data FROM {} WHERE table_name='narrative_edge_evidence' AND row_data->>'narrative_id'=%s ORDER BY row_ordinal").format(rows),(str(scratch_narrative),)).fetchall()
    for (raw,) in evidence:
        row=dict(raw); row['narrative_id']=ident
        row['entity_relation_id']=relation_map[int(row['entity_relation_id'])]
        if row.get('doc_id') is not None and not conn.execute('SELECT 1 FROM ingest_documents WHERE id=%s',(row['doc_id'],)).fetchone():
            raise ValueError('Evidence document is missing')
        evid=conn.execute("INSERT INTO ingest_narrative_evidence(source_row) VALUES ('{}') RETURNING id").fetchone()[0]
        row['id']=evid
        conn.execute('UPDATE ingest_narrative_evidence SET source_row=%s WHERE id=%s',(Jsonb(row),evid))
    conn.execute("UPDATE ingest_narrative_claims SET status='completed' WHERE topic=%s AND token=%s",(topic,token))
    conn.execute('UPDATE ingest_narrative_ledger_state SET dirty=TRUE')
    return True


def overlay_narrative_ledger(conn, source_schema):
    """Copy committed ledger rows into the current disposable staging schema."""
    _guard(conn)
    if not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',source_schema or ''):
        raise ValueError('Fixture source schema required')
    source=sql.Identifier(source_schema)
    if not conn.execute(sql.SQL('SELECT 1 FROM {}.ingest_narrative_ledger_state').format(source)).fetchone():
        return
    pairs=(('narratives','ingest_narrative_versions'),('narrative_edge_evidence','ingest_narrative_evidence'),
           ('entities','ingest_graph_entities'),('entity_relations','ingest_graph_relations'))
    for legacy,ledger in pairs:
        if not conn.execute('SELECT 1 FROM legacy_snapshot_tables WHERE table_name=%s',(legacy,)).fetchone():
            raise ValueError('Narrative projection input missing')
        entries=conn.execute(sql.SQL('SELECT id,source_row FROM {}.{} WHERE source_row IS NOT NULL ORDER BY id').format(source,sql.Identifier(ledger))).fetchall()
        for ident,row in entries:
            updated=conn.execute("UPDATE legacy_snapshot_rows SET row_data=%s WHERE table_name=%s AND row_data->>'id'=%s RETURNING 1",
                                 (Jsonb(row),legacy,str(ident))).fetchone()
            if not updated:
                conn.execute('INSERT INTO legacy_snapshot_rows SELECT %s,COALESCE(max(row_ordinal)+1,0),%s FROM legacy_snapshot_rows WHERE table_name=%s',
                             (legacy,Jsonb(row),legacy))
        conn.execute('UPDATE legacy_snapshot_tables SET row_count=(SELECT count(*) FROM legacy_snapshot_rows WHERE table_name=%s) WHERE table_name=%s',(legacy,legacy))
