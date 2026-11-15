"""Compare a small existing SQLite snapshot with disposable PostgreSQL.

Never modifies the source, never prints document content, and deliberately does
not implement migration, synchronization, or a production data loader.
"""
import argparse
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql

from pipeline.document_read import SQLiteDocumentReader
from pipeline.postgres_document_read import PostgreSQLDocumentReader
from routers import spine_feed


class _SnapshotConnection(sqlite3.Connection):
    # Existing readers own connections and close them. Keep this one transaction
    # alive across list and detail reads; explicitly close it in the caller.
    def close(self):
        pass


def compare(source: Path, dsn: str, size: int, include_ids: list[int] | None = None) -> dict:
    if os.getenv('REFACTOR_TEST_DISPOSABLE') != '1':
        raise ValueError('Disposable fixture opt-in required')
    params = psycopg.conninfo.conninfo_to_dict(dsn)
    if (params.get('host'), params.get('dbname'), params.get('user')) != ('pg', 'fixture', 'fixture'):
        raise ValueError('Only the isolated fixture database is accepted')
    if not 1 <= size <= 50:
        raise ValueError('Sample size must be between 1 and 50')
    if len(include_ids or []) > 10 or any(i <= 0 for i in include_ids or []):
        raise ValueError('At most ten positive extra document IDs are allowed')
    uri = source.resolve(strict=True).as_uri() + '?mode=ro'
    sqlite = sqlite3.connect(uri, uri=True, factory=_SnapshotConnection)
    sqlite.row_factory = sqlite3.Row
    schema = 'refactor_sample_' + uuid.uuid4().hex
    created = False
    try:
        sqlite.execute('PRAGMA query_only=ON')
        sqlite.execute('BEGIN')
        with patch.object(spine_feed, 'get_connection', return_value=sqlite):
            feed = spine_feed.get_feed(q=None, source=None, stock=None, industry=None,
                                       topic=None, page=1, size=size, days=None, sort='relevance')
        reader = SQLiteDocumentReader(lambda: sqlite)
        docs = {item.id: reader.get(item.id) for item in feed.items}
        for doc_id in include_ids or []:
            docs[doc_id] = reader.get(doc_id)
        if any(value is None for value in docs.values()):
            raise RuntimeError('Document disappeared within snapshot')
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        created = True
        def pg():
            return psycopg.connect(dsn, options=f'-c search_path={schema}')
        ddl = Path(__file__).resolve().parents[1] / 'backend/refactor_sql/document_projection.sql'
        with pg() as conn:
            conn.execute(ddl.read_text())
            for doc in docs.values():
                payload = json.dumps(doc.model_dump(mode='json'), ensure_ascii=False)
                conn.execute('INSERT INTO document_projection VALUES (%s,%s,%s,%s::jsonb)',
                             (doc.id, doc.source_type, doc.published_at or None, payload))
            for ordinal, item in enumerate(feed.items):
                payload = json.dumps(item.model_dump(mode='json'), ensure_ascii=False)
                conn.execute('INSERT INTO document_list_projection VALUES (%s,%s,%s::jsonb)',
                             (ordinal, item.id, payload))
        target = PostgreSQLDocumentReader(pg)
        page = target.list(page=1, size=size)
        same_list = [x.model_dump() for x in page.items] == [x.model_dump() for x in feed.items]
        same_detail = all(target.get(k).model_dump() == v.model_dump() for k, v in docs.items())
        if not same_list or not same_detail:
            raise AssertionError('Sample response mismatch')
        return {'source_total': feed.total, 'sample_rows': len(feed.items),
                'sample_unique_documents': len(docs), 'list_and_detail_match': True,
                'documents_with_content': sum(bool(d.content) for d in docs.values()),
                'documents_with_saved_summary': sum(bool(d.summary) for d in docs.values()),
                'documents_with_attachments': sum(bool(d.images) for d in docs.values()),
                'sample_total_only': page.total, 'source_read_only': True}
    finally:
        sqlite3.Connection.close(sqlite)
        if created:
            with psycopg.connect(dsn) as conn:
                conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--size', type=int, default=20)
    parser.add_argument('--include-id', type=int, action='append', default=[])
    args = parser.parse_args()
    try:
        result = compare(args.source, os.environ['REFACTOR_POSTGRES_DSN'], args.size, args.include_id)
    except Exception as exc:
        # Do not expose DSNs, source paths, or real document content on failure.
        print('sample comparison failed:', type(exc).__name__, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
