"""Import a disposable legacy document archive into the experimental write ledger.

The unchanged snapshot tables remain the source archive. This step does not
publish a new feed, copy media bytes, or connect an operational writer.
"""
import os
import re


def import_archived_documents(conn):
    database, schema = conn.execute('SELECT current_database(),current_schema()').fetchone()
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or database != 'fixture' or
            not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema)):
        raise ValueError('Disposable fixture schema required')
    if not conn.execute('SELECT 1 FROM snapshot_metadata WHERE singleton').fetchone():
        raise ValueError('A captured legacy snapshot is required')
    if conn.execute('SELECT 1 FROM ingest_documents LIMIT 1').fetchone():
        raise ValueError('Refusing import into a nonempty ledger')
    conn.execute('''INSERT INTO ingest_documents
        (id,source_type,source_id,title,url,published_at,raw_content,markdown,media_json,digest_status,content_hash)
        OVERRIDING SYSTEM VALUE
        SELECT (row_data->>'id')::bigint, row_data->>'source_type', row_data->>'source_id',
               COALESCE(row_data->>'title',''), COALESCE(row_data->>'url',''),
               COALESCE(row_data->>'published_at',''), COALESCE(row_data->>'raw_content',''),
               COALESCE(row_data->>'markdown',''),
               CASE WHEN COALESCE(row_data->>'media_json','')='' THEN NULL ELSE (row_data->>'media_json')::jsonb END,
               row_data->>'digest_status', COALESCE(row_data->>'content_hash','')
        FROM legacy_snapshot_rows WHERE table_name='raw_documents' ORDER BY row_ordinal''')
    # Legacy detail displays the latest result even when it does not match the
    # current document hash. Keep that display in the archive, but only treat a
    # hash-matching result as current in the write ledger.
    conn.execute('''INSERT INTO ingest_enrichments(document_id,revision,summary,model)
        SELECT DISTINCT ON (d.id) d.id, 1, e.row_data->>'summary', e.row_data->>'model'
        FROM legacy_snapshot_rows e JOIN ingest_documents d ON d.id=(e.row_data->>'doc_id')::bigint
        WHERE e.table_name='enrichments' AND d.content_hash <> ''
              AND e.row_data->>'content_hash'=d.content_hash
        ORDER BY d.id, (e.row_data->>'enriched_at') COLLATE "C" DESC NULLS LAST,
                 (e.row_data->>'id')::bigint DESC''')
    conn.execute("INSERT INTO ingest_enrichment_jobs(document_id,revision,status) "
                 "SELECT d.id,1,CASE WHEN e.document_id IS NULL THEN 'pending' ELSE 'done' END "
                 "FROM ingest_documents d LEFT JOIN ingest_enrichments e ON e.document_id=d.id")
    # Historical tokens remain only in the archive: imported jobs describe
    # state and transcript, but do not grant authority to resume a worker.
    conn.execute('''INSERT INTO ingest_youtube_jobs(document_id,revision,transcript,status,token,updated_at,error)
        SELECT d.id,1,j.row_data->>'transcript',j.row_data->>'status',NULL,
               COALESCE((j.row_data->>'updated_at')::double precision,0),j.row_data->>'error'
        FROM legacy_snapshot_rows j JOIN ingest_documents d ON d.id=(j.row_data->>'doc_id')::bigint
        WHERE j.table_name='youtube_digest_jobs' AND d.source_type='youtube' ''')
    conn.execute("SELECT setval(pg_get_serial_sequence('ingest_documents','id'), "
                 "GREATEST(COALESCE((SELECT max(id) FROM ingest_documents),0),1), "
                 "EXISTS(SELECT 1 FROM ingest_documents))")
    # The imported projection is the baseline, not a pending user change.
    conn.execute('UPDATE ingest_documents SET projected_version=projection_version')
    return conn.execute('SELECT count(*) FROM ingest_documents').fetchone()[0]
