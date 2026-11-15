"""Rebuild a dedicated synthetic-note fixture into the existing feed/search tables.

This deliberately cannot operate on a migrated snapshot. It omits real source
channels, entity links, media bytes and all non-note source types. Embeddings
are precomputed synthetic values; this module never invokes a model.
"""
import os
import re
import uuid
from datetime import datetime, timezone
from psycopg.types.json import Jsonb
from models.spine import FeedDocument


def rebuild(conn):
    database, schema = conn.execute('SELECT current_database(),current_schema()').fetchone()
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or database != 'fixture' or
            not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema)):
        raise ValueError('Disposable fixture schema required')
    # All this experiment's write paths acquire a row lock on documents first.
    conn.execute('LOCK TABLE ingest_documents IN SHARE MODE')
    if conn.execute("SELECT count(*) FROM ingest_documents WHERE source_type != 'note'").fetchone()[0]:
        raise ValueError('Only synthetic notes are supported')
    if conn.execute('SELECT count(*) FROM snapshot_metadata').fetchone()[0]:
        if not conn.execute("SELECT 1 FROM legacy_snapshot_tables WHERE table_name='__ingest_fixture__'").fetchone():
            raise ValueError('Refusing to replace another snapshot')
    generation = uuid.uuid4()
    rows = conn.execute('SELECT d.id,d.source_type,d.source_id,d.title,d.url,d.published_at,d.markdown,d.raw_content, '
                        'd.media_json,d.digest_status,e.summary,e.model '
                        'FROM ingest_documents d LEFT JOIN ingest_enrichments e '
                        'ON e.document_id=d.id AND e.revision=d.revision '
                        'ORDER BY d.published_at DESC,d.id').fetchall()
    for table in ('document_filter_order', 'document_entity_order', 'document_list_projection',
                  'document_projection', 'legacy_snapshot_rows', 'legacy_snapshot_tables',
                  'document_embeddings', 'document_embedding_metadata', 'snapshot_metadata'):
        conn.execute('DELETE FROM ' + table)
    conn.execute("INSERT INTO legacy_snapshot_tables VALUES ('__ingest_fixture__','[]'::jsonb,'fixture',0)")
    conn.execute("INSERT INTO legacy_snapshot_tables VALUES ('raw_documents','[]'::jsonb,'fixture',%s)", (len(rows),))
    for ordinal, (ident, source, source_id, title, url, published, markdown, raw, media, digest, summary, model) in enumerate(rows):
        doc = FeedDocument(id=ident, source_type=source, title=title, url=url, published_at=published,
                           content=markdown, summary=summary, channel='내 노트', images=media or [],
                           enrich_model=model, digest_status=digest, entities=[])
        payload = Jsonb(doc.model_dump(mode='json'))
        conn.execute('INSERT INTO document_projection VALUES (%s,%s,%s,%s,TRUE,ARRAY[]::text[])',
                     (ident, source, published, payload))
        conn.execute('INSERT INTO document_list_projection VALUES (%s,%s,%s)', (ordinal, ident, payload))
        conn.execute('INSERT INTO document_filter_order VALUES (%s,%s,%s)', ('note', ordinal, ordinal))
        raw_row = {'id': ident, 'source_type': source, 'source_id': source_id, 'title': title,
                   'url': url, 'published_at': published, 'markdown': markdown, 'raw_content': raw}
        conn.execute("INSERT INTO legacy_snapshot_rows VALUES ('raw_documents',%s,%s)", (ordinal, Jsonb(raw_row)))
    now = datetime.now(timezone.utc)
    conn.execute('INSERT INTO snapshot_metadata(singleton,snapshot_at,source_observed_at,document_count,list_row_count,generation_id) '
                 'VALUES (TRUE,%s,%s,%s,%s,%s)', (now.isoformat(), now, len(rows), len(rows), generation))
    conn.execute('INSERT INTO document_embeddings(document_id,embedding,content_hash) '
                 'SELECT d.id,e.embedding,d.content_hash FROM ingest_documents d '
                 'JOIN ingest_embeddings e ON e.document_id=d.id AND e.revision=d.revision')
    vector_count = conn.execute('SELECT count(*) FROM document_embeddings').fetchone()[0]
    conn.execute("INSERT INTO document_embedding_metadata VALUES (TRUE,%s,'synthetic-fixture',384,%s,0,0)",
                 (generation, vector_count))
    conn.execute('UPDATE ingest_documents SET projected_version=projection_version')
    return generation
