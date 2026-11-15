"""Build an isolated SQLite input for a new fixture snapshot from PG archive+ledger.

Only for small synthetic fixtures; in-memory reconstruction, no media bytes or
vectors. The original PG archive is not changed. Not a migration mechanism.
"""
import os
import re
import sqlite3


def materialize(conn):
    database, schema = conn.execute('SELECT current_database(),current_schema()').fetchone()
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or database != 'fixture' or
            not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema)):
        raise ValueError('Disposable fixture schema required')
    if (conn.execute('SHOW transaction_isolation').fetchone()[0] != 'repeatable read' or
            conn.execute('SHOW transaction_read_only').fetchone()[0] != 'on'):
        raise ValueError('A repeatable-read read-only source transaction is required')
    if conn.execute('SELECT count(*) FROM ingest_documents').fetchone()[0] > 1000:
        raise ValueError('In-memory bridge is restricted to small fixtures')
    if conn.execute('SELECT count(*) FROM document_embeddings').fetchone()[0]:
        raise ValueError('Fixture bridge does not support vectors')
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    try:
        tables = conn.execute('SELECT table_name,columns,schema_sql FROM legacy_snapshot_tables ORDER BY table_name').fetchall()
        for name, columns, ddl in tables:
            if not re.fullmatch(r'[a-z_][a-z0-9_]*', name) or not ddl.lstrip().upper().startswith('CREATE TABLE'):
                raise ValueError('Unsupported archived table schema')
            db.execute(ddl)
            names = ','.join('"' + c.replace('"', '""') + '"' for c in columns)
            placeholders = ','.join('?' for _ in columns)
            rows = conn.execute('SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s ORDER BY row_ordinal', (name,))
            db.executemany(f'INSERT INTO "{name}" ({names}) VALUES ({placeholders})',
                           (tuple(data.get(c) for c in columns) for (data,) in rows))
        raw_columns = {r['name'] for r in db.execute('PRAGMA table_info(raw_documents)')}
        en_columns = {r['name'] for r in db.execute('PRAGMA table_info(enrichments)')}
        rows = conn.execute('SELECT d.id,d.source_type,d.source_id,d.title,d.url,d.published_at,d.fetched_at,d.raw_content, '
                            'd.markdown,d.media_json,d.digest_status,d.content_hash,d.revision,e.summary,e.model '
                            'FROM ingest_documents d LEFT JOIN ingest_enrichments e '
                            'ON e.document_id=d.id AND e.revision=d.revision ORDER BY d.id')
        import json
        for ident,source,source_id,title,url,published,fetched,raw,markdown,media,status,digest,revision,summary,model in rows:
            existing = db.execute('SELECT id FROM raw_documents WHERE id=?', (ident,)).fetchone()
            if existing and revision == 1:
                # Media can change without changing the content revision.
                if 'media_json' in raw_columns:
                    db.execute('UPDATE raw_documents SET media_json=? WHERE id=?',
                               (json.dumps(media, ensure_ascii=False) if media else None,ident))
                continue
            values = {'id':ident,'source_type':source,'source_id':source_id,'title':title,'url':url,
                      'published_at':published,'fetched_at':fetched,'raw_content':raw,'markdown':markdown,
                      'media_json':json.dumps(media,ensure_ascii=False) if media else None,
                      'digest_status':status,'content_hash':digest}
            values = {k:v for k,v in values.items() if k in raw_columns}
            if existing:
                updates = ','.join(f'"{k}"=?' for k in values if k != 'id')
                db.execute(f'UPDATE raw_documents SET {updates} WHERE id=?',
                           tuple(v for k,v in values.items() if k != 'id')+(ident,))
                db.execute('DELETE FROM enrichments WHERE doc_id=?', (ident,))
                db.execute('DELETE FROM entity_links WHERE doc_id=?', (ident,))
                db.execute('DELETE FROM youtube_digest_jobs WHERE doc_id=?', (ident,))
            else:
                columns = ','.join(f'"{k}"' for k in values)
                db.execute(f'INSERT INTO raw_documents ({columns}) VALUES ({",".join("?" for _ in values)})', tuple(values.values()))
            if model is not None:
                enrichment = {'doc_id':ident,'summary':summary,'model':model,'content_hash':digest,
                              'enriched_at':'2026-01-01T00:00:00Z'}
                enrichment = {k:v for k,v in enrichment.items() if k in en_columns}
                columns = ','.join(f'"{k}"' for k in enrichment)
                db.execute(f'INSERT INTO enrichments ({columns}) VALUES ({",".join("?" for _ in enrichment)})', tuple(enrichment.values()))
            if source == 'youtube':
                job = conn.execute('SELECT transcript,status,token,updated_at,error FROM ingest_youtube_jobs '
                                   'WHERE document_id=%s AND revision=%s', (ident,revision)).fetchone()
                if job:
                    transcript,job_status,token,updated_at,error = job
                    # This SQLite database is a read-only projection input; its
                    # token is never a usable worker credential.
                    db.execute('INSERT INTO youtube_digest_jobs(doc_id,transcript,status,token,updated_at,error) '
                               'VALUES (?,?,?,?,?,?)', (ident,transcript,job_status,
                               str(token) if token else 'fixture-readonly',updated_at,error))
        db.commit()
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        return db
    except BaseException:
        db.close()
        raise
