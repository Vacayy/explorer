"""Apply all pending note changes to a freshly copied fixture projection.

Not an operational publisher: unsupported changes fail the transaction. Only
the note feed and document search are updated; no model or file is accessed.
"""
import json
import hashlib
from pathlib import Path
from psycopg import sql
from psycopg.types.json import Jsonb
from models.spine import FeedDocument
from pipeline.postgres_projection_copy_fixture import copy_projection
from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader
from pipeline.postgres_generation_media import _read_file


def copy_with_note_changes(conn, source_schema, target_schema, *, media_root=None):
    # copy_projection validates fixture schemas, empty target and isolation.
    result = copy_projection(conn, source_schema, target_schema)
    conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(source_schema)))
    reader = PostgreSQLRawDocumentReader(None)
    root = Path(media_root) if media_root is not None else None
    if root is not None and (root.is_symlink() or not root.is_dir()):
        raise ValueError('Invalid fixture media root')
    captured = {}
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
        media_changed = (prior.images if prior else []) != (media or [])
        if media_changed and media:
            if root is None:
                raise ValueError('Changed attachment files need a captured media root')
            for path in media:
                captured[path] = _read_file(root, path)
        same_revision = prior is not None and revision == 1
        if same_revision and media_changed and model is not None and (summary,model) != (prior.summary,prior.enrich_model):
            raise ValueError('Combined same-revision media and summary changes are ambiguous')
        if same_revision and not media_changed and model is None:
            raise ValueError('Same-revision changes require a current summary')
        doc = (prior or FeedDocument(id=ident,source_type='note',title='',url='',published_at='',summary=None,
                                     channel='내 노트',content=None,images=[],enrich_model=None,entities=[]))
        if same_revision:
            doc = doc.model_copy(update={'images':media or [], **({'summary':summary,'enrich_model':model} if not media_changed else {})})
        else:
            doc = doc.model_copy(update={'title':title,'url':url,'published_at':published,'content':markdown or raw,
                                         'images':media or [],'summary':summary,'enrich_model':model,'entities':[]})
        old_list = conn.execute('SELECT list_document FROM document_list_projection WHERE document_id=%s ORDER BY ordinal LIMIT 1', (ident,)).fetchone()
        list_content = old_list[0].get('content') if same_revision and old_list else markdown
        list_doc = doc.model_copy(update={'content':list_content})
        updates.append((ident,source_id,title,url,published,raw,markdown,media,status,digest,summary,model,
                        doc,list_doc,prior is not None,same_revision,media_changed))
    conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(target_schema)))
    if captured:
        conn.execute('INSERT INTO media_generations VALUES (%s) ON CONFLICT DO NOTHING', (result['generation'],))
        for path,body in captured.items():
            key = hashlib.sha256(body).hexdigest()
            conn.execute('INSERT INTO media_blobs VALUES (%s,%s) ON CONFLICT DO NOTHING', (key,body))
            conn.execute('INSERT INTO media_generation_refs VALUES (%s,%s,%s) '
                         'ON CONFLICT(generation_id,path) DO UPDATE SET digest=excluded.digest',
                         (result['generation'],path,key))
    conn.execute('CREATE TEMP TABLE overlay_old_list ON COMMIT DROP AS SELECT * FROM document_list_projection')
    conn.execute('CREATE TEMP TABLE overlay_old_filters ON COMMIT DROP AS SELECT * FROM document_filter_order')
    conn.execute('DELETE FROM document_filter_order')
    conn.execute('DELETE FROM document_list_projection')
    replaced_ids = [row[0] for row in updates if not (row[-2] and row[-1])]
    for ident,source_id,title,url,published,raw,markdown,media,status,digest,summary,model,doc,list_doc,existing,same_revision,media_changed in updates:
        if existing:
            if not same_revision:
                conn.execute('DELETE FROM document_entity_order WHERE document_id=%s', (ident,))
                conn.execute("DELETE FROM legacy_snapshot_rows WHERE table_name='entity_links' AND row_data->>'doc_id'=%s", (str(ident),))
                conn.execute('DELETE FROM document_embeddings WHERE document_id=%s', (ident,))
                conn.execute('DELETE FROM document_centroids WHERE document_id=%s', (ident,))
            if not same_revision or not media_changed:
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
        if same_revision and media_changed:
            old['media_json'] = json.dumps(media,ensure_ascii=False) if media else None
        if existing:
            conn.execute("UPDATE legacy_snapshot_rows SET row_data=%s WHERE table_name='raw_documents' AND row_data->>'id'=%s", (Jsonb(old),str(ident)))
        else:
            conn.execute("INSERT INTO legacy_snapshot_rows SELECT 'raw_documents',COALESCE(max(row_ordinal)+1,0),%s "
                         "FROM legacy_snapshot_rows WHERE table_name='raw_documents'", (Jsonb(old),))
        if model is not None and not (same_revision and media_changed):
            next_id = conn.execute("SELECT COALESCE(max((row_data->>'id')::bigint),0)+1 FROM legacy_snapshot_rows WHERE table_name='enrichments'").fetchone()[0]
            enrichment = {'id':next_id,'doc_id':ident,'summary':summary,'model':model,'content_hash':digest,
                          'enriched_at':'2026-01-01T00:00:00Z'}
            conn.execute("INSERT INTO legacy_snapshot_rows SELECT 'enrichments',COALESCE(max(row_ordinal)+1,0),%s "
                         "FROM legacy_snapshot_rows WHERE table_name='enrichments'", (Jsonb(enrichment),))
    conn.execute('CREATE TEMP TABLE overlay_new_rows(old_ordinal bigint,document_id bigint,list_document jsonb) ON COMMIT DROP')
    conn.execute('INSERT INTO overlay_new_rows SELECT ordinal,document_id,list_document FROM overlay_old_list '
                 'WHERE NOT (document_id=ANY(%s))', (replaced_ids,))
    for ident,*rest in updates:
        doc = rest[-4]
        if rest[-2] and rest[-1]:
            conn.execute("UPDATE overlay_new_rows SET list_document=jsonb_set(list_document,'{images}',%s) WHERE document_id=%s",
                         (Jsonb(doc.images),ident))
        else:
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
    conn.execute('''UPDATE document_embedding_metadata SET
        vector_count=(SELECT count(*) FROM document_embeddings),
        source_hash_missing_count=(SELECT count(*) FROM document_embeddings v JOIN legacy_snapshot_rows r
            ON r.table_name='raw_documents' AND r.row_data->>'id'=v.document_id::text
            WHERE r.row_data->>'content_hash' IS NULL),
        stale_count=(SELECT count(*) FROM document_embeddings v JOIN legacy_snapshot_rows r
            ON r.table_name='raw_documents' AND r.row_data->>'id'=v.document_id::text
            WHERE r.row_data->>'content_hash' IS NOT NULL AND v.content_hash IS DISTINCT FROM r.row_data->>'content_hash')''')
    conn.execute('UPDATE document_centroid_metadata SET vector_count=(SELECT count(*) FROM document_centroids)')
    result['updated_documents'] = len(updates)
    return result
