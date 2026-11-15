"""Copy selected videos from a consistent read-only SQLite snapshot to a fixture.

Not an incremental sync or production migration. Full source rows are retained
in a private archive alongside the normalized current display fields.
"""
import os
import re
from psycopg.types.json import Jsonb


def import_videos(source, target, ids):
    database, schema = target.execute('SELECT current_database(),current_schema()').fetchone()
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or database != 'fixture' or
            not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema)):
        raise ValueError('Disposable fixture schema required')
    if not source.in_transaction or source.execute('PRAGMA query_only').fetchone()[0] != 1:
        raise ValueError('Read-only SQLite transaction required')
    imported = 0
    for ident in dict.fromkeys(ids):
        doc = source.execute("SELECT * FROM raw_documents WHERE id=? AND source_type='youtube'", (ident,)).fetchone()
        if doc is None:
            raise ValueError('Requested video missing')
        doc = dict(doc)
        entries = [dict(row) for row in source.execute(
            'SELECT * FROM enrichments WHERE doc_id=? ORDER BY enriched_at DESC,id DESC', (ident,))]
        found_job = source.execute('SELECT * FROM youtube_digest_jobs WHERE doc_id=?', (ident,)).fetchone()
        job = dict(found_job) if found_job else None
        import json
        media = json.loads(doc['media_json']) if doc.get('media_json') else None
        target.execute('INSERT INTO ingest_documents(id,source_type,source_id,title,url,published_at,raw_content,markdown,media_json,digest_status,content_hash) '
                       'OVERRIDING SYSTEM VALUE VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (ident, doc['source_type'], doc['source_id'], doc.get('title') or '', doc.get('url') or '',
                        doc.get('published_at') or '', doc.get('raw_content') or '', doc.get('markdown') or '',
                        Jsonb(media) if media else None, doc.get('digest_status'), doc.get('content_hash') or ''))
        target.execute("INSERT INTO ingest_enrichment_jobs(document_id,revision,status) VALUES (%s,1,%s)",
                       (ident, 'done' if entries else 'pending'))
        if entries:
            target.execute('INSERT INTO ingest_enrichments VALUES (%s,1,%s,%s)',
                           (ident, entries[0].get('summary'), entries[0].get('model')))
        if job:
            # Historical tokens are preserved in the archive, not made runnable.
            target.execute('INSERT INTO ingest_youtube_jobs VALUES (%s,1,%s,%s,NULL,%s,%s)',
                           (ident, job.get('transcript'), job['status'], job.get('updated_at') or 0, job.get('error')))
        channel_id = doc['source_id'].split('/')[0] if '/' in doc['source_id'] else None
        if channel_id:
            channel = source.execute('SELECT title FROM youtube_channels WHERE channel_id=?', (channel_id,)).fetchone()
            if channel:
                target.execute('INSERT INTO ingest_youtube_channels VALUES (%s,%s) ON CONFLICT DO NOTHING',
                               (channel_id, channel['title'] or ''))
        target.execute('INSERT INTO ingest_legacy_video_archive VALUES (%s,%s,%s,%s)',
                       (ident, Jsonb(doc), Jsonb(entries), Jsonb(job) if job else None))
        imported += 1
    target.execute("SELECT setval(pg_get_serial_sequence('ingest_documents','id'), "
                   "GREATEST(COALESCE((SELECT max(id) FROM ingest_documents),0),1), "
                   "EXISTS(SELECT 1 FROM ingest_documents))")
    return imported
