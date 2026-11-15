"""Disposable narrative ledger initialization and stale-input claims.

No narrative result is committed by this module yet. Caller owns transactions.
"""
from hashlib import sha256
from uuid import uuid4
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
