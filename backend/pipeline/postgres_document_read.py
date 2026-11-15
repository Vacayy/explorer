"""Isolated PostgreSQL document read prototype; not connected to the live API.

The projections contain the existing response shape, including distinct list and
detail content. Populating them from actual source data is intentionally separate.
"""
from datetime import datetime, timezone

from models.spine import FeedDocument, FeedResponse


class PostgreSQLDocumentReader:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def get(self, doc_id: int) -> FeedDocument | None:
        with self.connection_factory() as conn:
            row = conn.execute(
                'SELECT detail_document FROM document_projection WHERE id = %s',
                (doc_id,),
            ).fetchone()
            return FeedDocument.model_validate(row[0]) if row else None

    def list(self, *, page: int = 1, size: int = 20, source: str | None = None) -> FeedResponse:
        if page < 1 or not 1 <= size <= 100:
            raise ValueError('page must be positive and size must be between 1 and 100')
        with self.connection_factory() as conn:
            # Count and page must describe one consistent snapshot.
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            if source in {'blog', 'news', 'article', 'people'}:
                where = 'WHERE d.feed_visible AND d.source_groups @> ARRAY[%s]::text[]'
            elif source:
                where = 'WHERE d.feed_visible AND d.source_type = %s'
            else:
                where = 'WHERE d.feed_visible'
            params = (source,) if source else ()
            total = conn.execute(f'SELECT count(*) FROM document_projection d {where}', params).fetchone()[0]
            rows = conn.execute(
                f'SELECT l.list_document FROM document_list_projection l '
                f'JOIN document_projection d ON d.id = l.document_id {where} '
                'ORDER BY d.published_at DESC NULLS LAST, l.ordinal ASC LIMIT %s OFFSET %s',
                (*params, size, (page - 1) * size),
            ).fetchall()
        return FeedResponse(items=[FeedDocument.model_validate(row[0]) for row in rows],
                            total=total, page=page, size=size,
                            as_of=datetime.now(timezone.utc).isoformat(), facets=None)

    def snapshot_info(self) -> dict | None:
        with self.connection_factory() as conn:
            row = conn.execute(
                'SELECT snapshot_at, document_count, list_row_count FROM snapshot_metadata WHERE singleton'
            ).fetchone()
            if row is None:
                return None
            return {'snapshot_at': row[0], 'documents': row[1], 'list_rows': row[2]}
