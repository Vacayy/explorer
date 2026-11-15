"""Apply all pending note changes to a freshly copied fixture projection.

Not an operational publisher: unsupported changes fail the transaction. Only
the note feed and document search are updated; no model or file is accessed.
"""
import json
from psycopg import sql
from psycopg.types.json import Jsonb
from models.spine import FeedDocument
from pipeline.postgres_projection_copy_fixture import copy_projection
from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader


def copy_with_note_changes(conn, source_schema, target_schema):
    # copy_projection validates fixture schemas, empty target and isolation.
    result = copy_projection(conn, source_schema, target_schema)
    conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(source_schema)))
    reader = PostgreSQLRawDocumentReader(None)
    dirty = conn.execute('SELECT d.id,d.source_type,d.source_id,d.title,d.url,d.published_at,d.raw_content, '
                         'd.markdown,d.media_json,d.digest_status,d.content_hash,d.revision,e.summary,e.model '
                         'FROM ingest_documents d LEFT JOIN ingest_enrichments e '
                         'ON e.document_id=d.id AND e.revision=d.revision '
                         'WHERE d.projection_version>d.projected_version ORDER BY d.id').fetchall()
    updates = []
    for ident,source,source_id,title,url,published,raw,markdown,media,status,digest,revision,summary,model in dirty:
        if source != 'note':
            raise ValueError('Only note changes are supported')
        if conn.execute('SELECT 1 FROM timeline_source_projection WHERE document_id=%s', (ident,)).fetchone():
            raise ValueError('Timeline changes are not supported')
        prior = reader.get_in_transaction(conn, ident)
        if (prior.images if prior else []) != (media or []):
            raise ValueError('Changed attachment files are not supported')
        same_revision = prior is not None and revision == 1
        if same_revision and model is None:
            raise ValueError('Same-revision changes require a current summary')
        doc = (prior or FeedDocument(id=ident,source_type='note',title='',url='',published_at='',summary=None,
                                     channel='내 노트',content=None,images=[],enrich_model=None,entities=[]))
        if same_revision:
            doc = doc.model_copy(update={'summary':summary,'enrich_model':model})
        else:
            doc = doc.model_copy(update={'title':title,'url':url,'published_at':published,'content':markdown or raw,
                                         'images':media or [],'summary':summary,'enrich_model':model,'entities':[]})
        updates.append((ident,source_id,title,url,published,raw,markdown,media,status,digest,summary,model,doc,prior is not None,same_revision))
    conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(target_schema)))
    conn.execute('CREATE TEMP TABLE overlay_old_list ON COMMIT DROP AS SELECT * FROM document_list_projection')
    conn.execute('CREATE TEMP TABLE overlay_old_filters ON COMMIT DROP AS SELECT * FROM document_filter_order')
    conn.execute('DELETE FROM document_filter_order')
    conn.execute('DELETE FROM document_list_projection')
    changed_ids = [row[0] for row in updates]
    for ident,source_id,title,url,published,raw,markdown,media,status,digest,summary,model,doc,existing,same_revision in updates:
        if existing:
            if not same_revision:
                conn.execute('DELETE FROM document_entity_order WHERE document_id=%s', (ident,))
                conn.execute("DELETE FROM legacy_snapshot_rows WHERE table_name='entity_links' AND row_data->>'doc_id'=%s", (str(ident),))
                conn.execute('DELETE FROM document_embeddings WHERE document_id=%s', (ident,))
                conn.execute('DELETE FROM document_centroids WHERE document_id=%s', (ident,))
            conn.execute("DELETE FROM legacy_snapshot_rows WHERE table_name='enrichments' AND row_data->>'doc_id'=%s", (str(ident),))
            if same_revision:
                conn.execute('UPDATE document_projection SET detail_document=%s WHERE id=%s',
                             (Jsonb(doc.model_dump(mode='json')),ident))
            else:
                conn.execute('UPDATE document_projection SET published_at=%s,detail_document=%s WHERE id=%s',
                             (published,Jsonb(doc.model_dump(mode='json')),ident))
            old = conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' AND row_data->>'id'=%s", (str(ident),)).fetchone()[0]
        else:
            conn.execute('INSERT INTO document_projection VALUES (%s,%s,%s,%s,TRUE,ARRAY[]::text[])',
                         (ident,'note',published,Jsonb(doc.model_dump(mode='json'))))
            old = {}
        if not same_revision:
            old.update({'id':ident,'source_type':'note','source_id':source_id,'title':title,'url':url,
                        'published_at':published,'raw_content':raw,'markdown':markdown,'content_hash':digest,
                        'media_json':json.dumps(media,ensure_ascii=False) if media else None,'digest_status':status})
        if existing:
            conn.execute("UPDATE legacy_snapshot_rows SET row_data=%s WHERE table_name='raw_documents' AND row_data->>'id'=%s", (Jsonb(old),str(ident)))
        else:
            conn.execute("INSERT INTO legacy_snapshot_rows SELECT 'raw_documents',COALESCE(max(row_ordinal)+1,0),%s "
                         "FROM legacy_snapshot_rows WHERE table_name='raw_documents'", (Jsonb(old),))
        if model is not None:
            next_id = conn.execute("SELECT COALESCE(max((row_data->>'id')::bigint),0)+1 FROM legacy_snapshot_rows WHERE table_name='enrichments'").fetchone()[0]
            enrichment = {'id':next_id,'doc_id':ident,'summary':summary,'model':model,'content_hash':digest,
                          'enriched_at':'2026-01-01T00:00:00Z'}
            conn.execute("INSERT INTO legacy_snapshot_rows SELECT 'enrichments',COALESCE(max(row_ordinal)+1,0),%s "
                         "FROM legacy_snapshot_rows WHERE table_name='enrichments'", (Jsonb(enrichment),))
    conn.execute('CREATE TEMP TABLE overlay_new_rows(old_ordinal bigint,document_id bigint,list_document jsonb) ON COMMIT DROP')
    conn.execute('INSERT INTO overlay_new_rows SELECT ordinal,document_id,list_document FROM overlay_old_list '
                 'WHERE NOT (document_id=ANY(%s))', (changed_ids,))
    for ident,*rest in updates:
        doc = rest[-3]
        conn.execute('INSERT INTO overlay_new_rows VALUES (NULL,%s,%s)', (ident,Jsonb(doc.model_dump(mode='json'))))
    conn.execute('''CREATE TEMP TABLE overlay_ord ON COMMIT DROP AS
        SELECT row_number() OVER (ORDER BY d.published_at COLLATE "C" DESC NULLS LAST,
                                      n.old_ordinal NULLS LAST,n.document_id)-1 AS ordinal,
               n.old_ordinal,n.document_id,n.list_document
        FROM overlay_new_rows n JOIN document_projection d ON d.id=n.document_id''')
    conn.execute('INSERT INTO document_list_projection SELECT ordinal,document_id,list_document FROM overlay_ord')
    conn.execute("INSERT INTO document_filter_order SELECT f.filter_key,f.position,n.ordinal FROM overlay_old_filters f "
                 "JOIN overlay_ord n ON n.old_ordinal=f.list_ordinal WHERE f.filter_key<>'note'")
    conn.execute("INSERT INTO document_filter_order SELECT 'note',row_number() OVER (ORDER BY n.ordinal)-1,n.ordinal "
                 "FROM overlay_ord n JOIN document_projection d ON d.id=n.document_id WHERE d.source_type='note'")
    conn.execute("UPDATE legacy_snapshot_tables t SET row_count=(SELECT count(*) FROM legacy_snapshot_rows r WHERE r.table_name=t.table_name) "
                 "WHERE table_name IN ('raw_documents','enrichments','entity_links')")
    conn.execute('UPDATE snapshot_metadata SET document_count=(SELECT count(*) FROM document_projection), '
                 'list_row_count=(SELECT count(*) FROM document_list_projection)')
    conn.execute('UPDATE document_embedding_metadata SET vector_count=(SELECT count(*) FROM document_embeddings)')
    conn.execute('UPDATE document_centroid_metadata SET vector_count=(SELECT count(*) FROM document_centroids)')
    result['updated_documents'] = len(updates)
    return result
