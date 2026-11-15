"""Apply supported changes to a freshly copied fixture projection.

Not an operational publisher: unsupported changes fail the transaction. New
notes and existing blog/video changes are limited to the documented cases.
"""
import json
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from psycopg import sql
from psycopg.types.json import Jsonb
from models.spine import EntityTag, FeedDocument
from pipeline.postgres_projection_copy_fixture import copy_projection
from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader
from pipeline.postgres_generation_media import _read_file
from pipeline.youtube_digest import fields_from_job
from pipeline.sources import source_names_from_rows
from pipeline.timeline import utc
from pipeline.urls import blog_category, is_feedlike, norm_domain, url_belongs


def _new_source_details(conn, ident, source, source_id, url, published, fetched=None):
    """Reproduce existing source registry, visibility, and timeline rules."""
    blogs = [r[0] for r in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='blog_sources'")]
    youtube = [r[0] for r in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='youtube_channels'")]
    blog_names = sorted(((r['url'],r['blog_name'] or r['url']) for r in blogs), key=lambda x: len(x[0] or ''), reverse=True)
    yt_names = {r['channel_id']:r['title'] for r in youtube}
    channel = source_names_from_rows([{'id':ident,'source_type':source,'source_id':source_id,'url':url}],
                                     telegram={},blogs=blog_names,youtube=yt_names,scraps={}).get(ident) or {}
    groups = set()
    visible = True
    timeline_key = None
    with sqlite3.connect(':memory:') as sqlite:
        def like(pattern): return bool(sqlite.execute('SELECT ? LIKE ?', (url,pattern)).fetchone()[0])
        if source == 'blog':
            for row in blogs:
                source_url,platform = row['url'],row['platform']
                if row['is_active'] == 0:
                    pattern = '%//%' + norm_domain(source_url) + '%' if is_feedlike(source_url) else source_url + '%'
                    if like(pattern): visible = False
                pattern = '%//%' + norm_domain(source_url) + '%' if platform == 'rss' else source_url + '%'
                if like(pattern): groups.add(blog_category(source_url,platform))
            matched = [row for row in blogs if url_belongs(url,row['url'])]
            if any(row['is_active'] == 1 for row in matched) and not any(row['is_active'] == 0 for row in matched):
                timeline_key = channel.get('key') or ''
        elif source == 'youtube':
            channel_id = source_id.split('/',1)[0] if '/' in source_id else ''
            if any(row['channel_id'] == channel_id and row['is_active'] == 1 for row in youtube):
                timeline_key = channel_id
    if timeline_key is not None:
        stamp = published or fetched
        if not stamp:
            raise ValueError('Timeline sources need an explicit published or fetched time')
        try:
            occurred = utc(stamp)
            instant = datetime.fromisoformat(occurred)
        except (ValueError,TypeError,AttributeError) as exc:
            raise ValueError('Unsupported publication time') from exc
        delta = instant-datetime(1970,1,1,tzinfo=timezone.utc)
        millis = ((delta.days*86400+delta.seconds)*1000000+delta.microseconds+500)//1000
        timeline = (timeline_key,occurred,millis,'게시' if published else '수집')
    else:
        timeline = None
    return channel,sorted(groups),visible,timeline


def copy_with_note_changes(conn, source_schema, target_schema, *, media_root=None):
    # copy_projection validates fixture schemas, empty target and isolation.
    result = copy_projection(conn, source_schema, target_schema)
    conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(source_schema)))
    reader = PostgreSQLRawDocumentReader(None)
    root = Path(media_root) if media_root is not None else None
    if root is not None and (root.is_symlink() or not root.is_dir()):
        raise ValueError('Invalid fixture media root')
    captured = {}
    metadata = conn.execute('SELECT expected_model,vector_count,generation_id FROM document_embedding_metadata WHERE singleton').fetchone()
    graph_ready=bool(conn.execute('SELECT 1 FROM ingest_graph_state').fetchone())
    if graph_ready:
        new_entities=conn.execute("SELECT g.id,g.type,g.name,g.aliases,g.status FROM ingest_graph_entities g "
                                  "WHERE NOT EXISTS(SELECT 1 FROM legacy_snapshot_rows a WHERE a.table_name='entities' AND a.row_data->>'id'=g.id::text) ORDER BY g.id").fetchall()
        new_keywords=conn.execute("SELECT g.entity_id,g.keyword,g.status FROM ingest_graph_keywords g "
                                  "WHERE NOT EXISTS(SELECT 1 FROM legacy_snapshot_rows a WHERE a.table_name='entity_keywords' "
                                  "AND a.row_data->>'entity_id'=g.entity_id::text AND a.row_data->>'keyword'=g.keyword)").fetchall()
        new_relations=conn.execute('SELECT id,src_id,dst_id,rel_type,epistemic_type,confidence,source_doc_id,valid_from '
                                   'FROM ingest_graph_relations WHERE source_ordinal IS NULL ORDER BY id').fetchall()
    else:
        new_entities,new_keywords,new_relations=[],[],[]
    dirty = conn.execute('SELECT d.id,d.source_type,d.source_id,d.title,d.url,d.published_at,d.fetched_at,d.raw_content, '
                         'd.markdown,d.media_json,d.digest_status,d.content_hash,d.revision,e.summary,e.model, '
                         'd.enrichment_dirty,d.embedding_dirty,v.embedding,v.model,d.links_dirty '
                         'FROM ingest_documents d LEFT JOIN ingest_enrichments e '
                         'ON e.document_id=d.id AND e.revision=d.revision '
                         'LEFT JOIN ingest_embeddings v ON v.document_id=d.id AND v.revision=d.revision '
                         'WHERE d.projection_version>d.projected_version ORDER BY d.id').fetchall()
    updates = []
    for ident,source,source_id,title,url,published,fetched,raw,markdown,media,status,digest,revision,summary,model,enrichment_dirty,embedding_dirty,embedding,embedding_model,links_dirty in dirty:
        if embedding_dirty and (embedding is None or metadata is None or embedding_model != metadata[0]):
            raise ValueError('Embedding is missing or uses a different model')
        if embedding_dirty and metadata[1] > 0:
            attestation = conn.execute('SELECT profile FROM embedding_profile_attestations WHERE generation_id=%s',
                                       (metadata[2],)).fetchone()
            if attestation is None or attestation[0] != 'fixture:' + embedding_model:
                raise ValueError('Existing vector profile is not verified for mixing')
        if source not in ('note','blog','youtube'):
            raise ValueError('Unsupported source change')
        timeline_present = bool(conn.execute('SELECT 1 FROM timeline_source_projection WHERE document_id=%s', (ident,)).fetchone())
        prior = reader.get_in_transaction(conn, ident)
        media_changed = (prior.images if prior else []) != (media or [])
        if media_changed and media:
            if root is None:
                raise ValueError('Changed attachment files need a captured media root')
            for path in media:
                captured[path] = _read_file(root, path)
        same_revision = prior is not None and revision == 1
        original = None
        if source != 'note' and prior is not None and not same_revision:
            original = conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' AND row_data->>'id'=%s", (str(ident),)).fetchone()[0]
            if (original.get('source_id') or '') != source_id:
                raise ValueError('Source identity changes are unsupported')
        if timeline_present and source == 'note':
            raise ValueError('Timeline content changes are not supported')
        if same_revision and media_changed and enrichment_dirty:
            raise ValueError('Combined same-revision media and summary changes are ambiguous')
        if same_revision and enrichment_dirty and model is None:
            raise ValueError('Same-revision changes require a current summary')
        if source != 'note' and (prior is None or not same_revision):
            channel,groups,visible,timeline = _new_source_details(conn,ident,source,source_id,url,published,fetched)
        elif prior is None:
            channel,groups,visible,timeline = {'name':'내 노트'},[],True,None
        else:
            projection = conn.execute('SELECT source_groups,feed_visible FROM document_projection WHERE id=%s',(ident,)).fetchone()
            channel,groups,visible,timeline = {},projection[0],projection[1],None
        link_rows=[]
        if links_dirty:
            links = conn.execute("SELECT l.entity_id,l.link_type,l.confidence,COALESCE(to_jsonb(g),e.row_data) FROM ingest_entity_links l "
                                 "LEFT JOIN ingest_graph_entities g ON g.id=l.entity_id "
                                 "LEFT JOIN legacy_snapshot_rows e ON e.table_name='entities' AND e.row_data->>'id'=l.entity_id::text "
                                 "WHERE l.document_id=%s AND l.revision=%s ORDER BY l.position",(ident,revision)).fetchall()
            expected=conn.execute('SELECT count(*) FROM ingest_entity_links WHERE document_id=%s AND revision=%s',(ident,revision)).fetchone()[0]
            if len(links) != expected or any(row[3] is None for row in links):
                raise ValueError('An entity link no longer resolves')
            link_rows=[EntityTag(entity_id=eid,type=entity['type'],name=entity['name'],aliases=entity.get('aliases'),
                                 link_type=kind,confidence=confidence) for eid,kind,confidence,entity in links]
            followed={int(r[0]['entity_id']) for r in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='follows'")}
            groups=[group for group in groups if group != 'people']
            if any(link.link_type == 'person' and link.entity_id in followed for link in link_rows):
                groups=sorted([*groups,'people'])
        doc = (prior or FeedDocument(id=ident,source_type=source,title='',url='',published_at='',summary=None,
                                     channel=channel.get('name'),channel_kind=channel.get('kind'),
                                     channel_key=channel.get('key'),content=None,images=[],enrich_model=None,entities=[]))
        if same_revision:
            doc = doc.model_copy(update={'images':media or [], **({'summary':summary,'enrich_model':model} if enrichment_dirty else {})})
        else:
            doc = doc.model_copy(update={'title':title,'url':url,'published_at':published,'content':markdown or raw,
                                         'images':media or [],'summary':summary,'enrich_model':model,'entities':[]})
            if source != 'note':
                doc = doc.model_copy(update={'channel':channel.get('name'),'channel_kind':channel.get('kind'),
                                             'channel_key':channel.get('key')})
            if source == 'youtube':
                job = conn.execute('SELECT transcript,status,updated_at,error FROM ingest_youtube_jobs WHERE document_id=%s AND revision=%s',
                                   (ident,revision)).fetchone()
                job = dict(zip(('transcript','status','updated_at','error'),job)) if job else None
                doc = doc.model_copy(update=fields_from_job({'source_type':source,'digest_status':status,
                                                            'markdown':markdown,'raw_content':raw},job))
        if links_dirty:
            doc = doc.model_copy(update={'entities':link_rows})
        old_list = conn.execute('SELECT list_document FROM document_list_projection WHERE document_id=%s ORDER BY ordinal LIMIT 1', (ident,)).fetchone()
        list_content = old_list[0].get('content') if same_revision and old_list else markdown
        list_doc = doc.model_copy(update={'content':list_content})
        if source == 'youtube':
            list_doc = list_doc.model_copy(update={'digest_status':None,'digest_error':None,'video_digest':None,'transcript':None})
        updates.append((ident,source,source_id,title,url,published,fetched,raw,markdown,media,status,digest,summary,model,
                        enrichment_dirty,embedding_dirty,bytes(embedding) if embedding is not None else None,links_dirty,
                        groups,visible,timeline,doc,list_doc,prior is not None,same_revision,media_changed))
    conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(target_schema)))
    for ident,kind,name,aliases,status in new_entities:
        value={'id':ident,'type':kind,'name':name,'aliases':aliases,'status':status,'meta_json':None}
        conn.execute("INSERT INTO legacy_snapshot_rows SELECT 'entities',COALESCE(max(row_ordinal)+1,0),%s "
                     "FROM legacy_snapshot_rows WHERE table_name='entities'",(Jsonb(value),))
    for ident,keyword,status in new_keywords:
        value={'entity_id':ident,'keyword':keyword,'status':status}
        conn.execute("INSERT INTO legacy_snapshot_rows SELECT 'entity_keywords',COALESCE(max(row_ordinal)+1,0),%s "
                     "FROM legacy_snapshot_rows WHERE table_name='entity_keywords'",(Jsonb(value),))
    for ident,src,dst,kind,epistemic,confidence,doc_id,valid_from in new_relations:
        value={'id':ident,'src_id':src,'dst_id':dst,'rel_type':kind,'epistemic_type':epistemic,
               'confidence':confidence,'source_doc_id':doc_id,'valid_from':valid_from}
        conn.execute("INSERT INTO legacy_snapshot_rows SELECT 'entity_relations',COALESCE(max(row_ordinal)+1,0),%s "
                     "FROM legacy_snapshot_rows WHERE table_name='entity_relations'",(Jsonb(value),))
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
    # Same-revision media/vector-only updates must retain duplicate legacy feed rows.
    replaced_ids = [row[0] for row in updates if not (row[-2] and not row[14])]
    for ident,source,source_id,title,url,published,fetched,raw,markdown,media,status,digest,summary,model,enrichment_dirty,embedding_dirty,embedding,links_dirty,groups,visible,timeline,doc,list_doc,existing,same_revision,media_changed in updates:
        if existing:
            if not same_revision or links_dirty:
                conn.execute('DELETE FROM document_entity_order WHERE document_id=%s', (ident,))
                conn.execute("DELETE FROM legacy_snapshot_rows WHERE table_name='entity_links' AND row_data->>'doc_id'=%s", (str(ident),))
            if not same_revision:
                conn.execute('DELETE FROM document_embeddings WHERE document_id=%s', (ident,))
                conn.execute('DELETE FROM document_centroids WHERE document_id=%s', (ident,))
            if not same_revision or enrichment_dirty:
                conn.execute("DELETE FROM legacy_snapshot_rows WHERE table_name='enrichments' AND row_data->>'doc_id'=%s", (str(ident),))
            if same_revision:
                conn.execute('UPDATE document_projection SET detail_document=%s,source_groups=%s WHERE id=%s',
                             (Jsonb(doc.model_dump(mode='json')),groups,ident))
            else:
                conn.execute('UPDATE document_projection SET published_at=%s,detail_document=%s,source_groups=%s,feed_visible=%s WHERE id=%s',
                             (published,Jsonb(doc.model_dump(mode='json')),groups,visible,ident))
            old = conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' AND row_data->>'id'=%s", (str(ident),)).fetchone()[0]
        else:
            conn.execute('INSERT INTO document_projection VALUES (%s,%s,%s,%s,%s,%s)',
                         (ident,source,published,Jsonb(doc.model_dump(mode='json')),visible,groups))
            old = {}
        if not same_revision:
            old.update({'id':ident,'source_type':source,'source_id':source_id,'title':title,'url':url,
                        'published_at':published,'fetched_at':fetched,'raw_content':raw,'markdown':markdown,'content_hash':digest,
                        'media_json':json.dumps(media,ensure_ascii=False) if media else None,'digest_status':status})
        if same_revision and media_changed:
            old['media_json'] = json.dumps(media,ensure_ascii=False) if media else None
        if existing:
            conn.execute("UPDATE legacy_snapshot_rows SET row_data=%s WHERE table_name='raw_documents' AND row_data->>'id'=%s", (Jsonb(old),str(ident)))
        else:
            conn.execute("INSERT INTO legacy_snapshot_rows SELECT 'raw_documents',COALESCE(max(row_ordinal)+1,0),%s "
                         "FROM legacy_snapshot_rows WHERE table_name='raw_documents'", (Jsonb(old),))
        next_id = None
        if model is not None and (not same_revision or enrichment_dirty):
            next_id = conn.execute("SELECT COALESCE(max((row_data->>'id')::bigint),0)+1 FROM legacy_snapshot_rows WHERE table_name='enrichments'").fetchone()[0]
            enrichment = {'id':next_id,'doc_id':ident,'summary':summary,'model':model,'content_hash':digest,
                          'enriched_at':'2026-01-01T00:00:00Z'}
            conn.execute("INSERT INTO legacy_snapshot_rows SELECT 'enrichments',COALESCE(max(row_ordinal)+1,0),%s "
                         "FROM legacy_snapshot_rows WHERE table_name='enrichments'", (Jsonb(enrichment),))
        if existing and not same_revision and source == 'note':
            conn.execute("UPDATE timeline_source_projection SET document=%s || jsonb_build_object('published_at',document->'published_at'), "
                         "preview=left(COALESCE(NULLIF(%s,''),NULLIF(%s,''),''),180),topic_names=ARRAY[]::text[] WHERE document_id=%s",
                         (Jsonb(list_doc.model_dump(mode='json')),title,markdown,ident))
            conn.execute("UPDATE timeline_source_metadata SET enrichment_id=%s,entity_order='[]'::jsonb WHERE document_id=%s", (next_id,ident))
        elif same_revision and enrichment_dirty and model is not None:
            conn.execute("UPDATE timeline_source_projection SET document=jsonb_set(jsonb_set(document,'{summary}',%s),'{enrich_model}',%s) "
                         "WHERE document_id=%s", (Jsonb(summary),Jsonb(model),ident))
            conn.execute('UPDATE timeline_source_metadata SET enrichment_id=%s WHERE document_id=%s', (next_id,ident))
        elif same_revision and media_changed:
            conn.execute("UPDATE timeline_source_projection SET document=jsonb_set(document,'{images}',%s) WHERE document_id=%s", (Jsonb(media or []),ident))
        if existing and not same_revision and source != 'note':
            conn.execute('DELETE FROM timeline_source_projection WHERE document_id=%s',(ident,))
            conn.execute('DELETE FROM timeline_source_metadata WHERE document_id=%s',(ident,))
        if timeline:
            key,occurred,millis,label = timeline
            timeline_doc = list_doc.model_copy(update={'published_at':occurred})
            conn.execute('INSERT INTO timeline_source_projection VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                         (f'source:{ident}',ident,occurred,millis,f'{source}:{key}',source,[],
                          label,(title or markdown or '')[:180],Jsonb(timeline_doc.model_dump(mode='json'))))
            conn.execute("INSERT INTO timeline_source_metadata VALUES (%s,%s,'[]'::jsonb)",(ident,next_id))
        if links_dirty:
            for position,link in enumerate(doc.entities):
                linkrow={'doc_id':ident,'entity_id':link.entity_id,'link_type':link.link_type,'confidence':link.confidence}
                conn.execute("INSERT INTO legacy_snapshot_rows SELECT 'entity_links',COALESCE(max(row_ordinal)+1,0),%s "
                             "FROM legacy_snapshot_rows WHERE table_name='entity_links'",(Jsonb(linkrow),))
                conn.execute('INSERT INTO document_entity_order VALUES (%s,%s,%s,%s,%s,0)',
                             (ident,position,link.entity_id,link.link_type,link.confidence))
            ordered=[{'entity_id':link.entity_id,'link_type':link.link_type,'confidence':link.confidence} for link in doc.entities]
            conn.execute("UPDATE timeline_source_projection SET document=jsonb_set(document,'{entities}',%s),topic_names=%s WHERE document_id=%s",
                         (Jsonb([link.model_dump(mode='json') for link in doc.entities]),sorted({link.name for link in doc.entities}),ident))
            conn.execute('UPDATE timeline_source_metadata SET entity_order=%s WHERE document_id=%s',(Jsonb(ordered),ident))
        if embedding_dirty:
            conn.execute('INSERT INTO document_embeddings(document_id,embedding,content_hash) VALUES (%s,%s,%s) '
                         'ON CONFLICT(document_id) DO UPDATE SET embedding=excluded.embedding,content_hash=excluded.content_hash',
                         (ident,embedding,digest))
    conn.execute('CREATE TEMP TABLE overlay_new_rows(old_ordinal bigint,document_id bigint,list_document jsonb) ON COMMIT DROP')
    conn.execute('INSERT INTO overlay_new_rows SELECT ordinal,document_id,list_document FROM overlay_old_list '
                 'WHERE NOT (document_id=ANY(%s))', (replaced_ids,))
    for row in updates:
        ident,doc,visible,existing,same_revision,media_changed,enrichment_dirty = row[0],row[-4],row[-7],row[-3],row[-2],row[-1],row[14]
        if not visible:
            continue
        if same_revision and not enrichment_dirty:
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
    moved_ids = [row[0] for row in updates if row[1] != 'note' and not row[-2]]
    relinked_ids = [row[0] for row in updates if row[17]]
    conn.execute('''INSERT INTO document_filter_order
        SELECT filter_key,row_number() OVER (PARTITION BY filter_key ORDER BY old_position,ordinal)-1,ordinal
        FROM (
            SELECT f.filter_key,f.position AS old_position,n.ordinal FROM overlay_old_filters f
            JOIN overlay_ord n ON n.old_ordinal=f.list_ordinal WHERE f.filter_key<>'note'
            UNION ALL
            SELECT f.filter_key,min(f.position),n.ordinal FROM overlay_old_filters f
            JOIN overlay_old_list l ON l.ordinal=f.list_ordinal
            JOIN overlay_ord n ON n.document_id=l.document_id AND n.old_ordinal IS NULL
            WHERE f.filter_key<>'note' AND NOT(l.document_id=ANY(%s))
              AND NOT(f.filter_key='people' AND l.document_id=ANY(%s)) GROUP BY f.filter_key,n.ordinal
        ) membership''',(moved_ids,relinked_ids))
    # New non-note sources have no old filter membership. Merge them by date;
    # existing positions remain the tie-breaker within each source filter.
    conn.execute('CREATE TEMP TABLE overlay_new_filters(filter_key text,document_id bigint) ON COMMIT DROP')
    for row in updates:
        ident,source,groups,visible,existing = row[0],row[1],row[-8],row[-7],row[-3]
        if visible and source != 'note' and (not existing or not row[-2]):
            for key in (groups if source == 'blog' else [source,*(['people'] if 'people' in groups else [])]):
                conn.execute('INSERT INTO overlay_new_filters VALUES (%s,%s)',(key,ident))
        elif visible and row[17] and 'people' in groups:
            conn.execute("INSERT INTO overlay_new_filters VALUES ('people',%s)",(ident,))
    if conn.execute('SELECT EXISTS(SELECT 1 FROM overlay_new_filters)').fetchone()[0]:
        conn.execute('CREATE TEMP TABLE overlay_existing_filters ON COMMIT DROP AS SELECT * FROM document_filter_order')
        conn.execute("DELETE FROM document_filter_order WHERE filter_key IN (SELECT filter_key FROM overlay_new_filters)")
        conn.execute('''INSERT INTO document_filter_order
            SELECT key,row_number() OVER (PARTITION BY key ORDER BY published_at COLLATE "C" DESC NULLS LAST,old_position NULLS LAST,ordinal)-1,ordinal
            FROM (
                SELECT f.filter_key AS key,f.position AS old_position,f.list_ordinal AS ordinal,d.published_at
                FROM overlay_existing_filters f JOIN document_list_projection l ON l.ordinal=f.list_ordinal
                JOIN document_projection d ON d.id=l.document_id WHERE f.filter_key IN (SELECT filter_key FROM overlay_new_filters)
                UNION ALL
                SELECT f.filter_key,NULL,n.ordinal,d.published_at FROM overlay_new_filters f
                JOIN overlay_ord n ON n.document_id=f.document_id AND n.old_ordinal IS NULL
                JOIN document_projection d ON d.id=n.document_id
            ) membership''')
    conn.execute("INSERT INTO document_filter_order SELECT 'note',row_number() OVER (ORDER BY n.ordinal)-1,n.ordinal "
                 "FROM overlay_ord n JOIN document_projection d ON d.id=n.document_id WHERE d.source_type='note'")
    conn.execute("UPDATE legacy_snapshot_tables t SET row_count=(SELECT count(*) FROM legacy_snapshot_rows r WHERE r.table_name=t.table_name) "
                 "WHERE table_name IN ('raw_documents','enrichments','entity_links','entities','entity_keywords','entity_relations')")
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
