"""Isolated PostgreSQL document read prototype; not connected to the live API.

The projections contain the existing response shape, including distinct list and
detail content. Populating them from actual source data is intentionally separate.
"""
from datetime import datetime, timezone
from contextlib import closing
import sqlite3

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

    def list(self, *, page: int = 1, size: int = 20, source: str | None = None,
             stock: str | None = None, industry: str | None = None,
             topic: str | None = None, days: int | None = None) -> FeedResponse:
        if page < 1 or not 1 <= size <= 100 or (days is not None and not 1 <= days <= 3650):
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
            params = [source] if source else []
            for link_type, field, value in (('stock', 'aliases', stock), ('industry', 'name', industry), ('topic', 'name', topic)):
                if not value:
                    continue
                where += (" AND EXISTS (SELECT 1 FROM legacy_snapshot_rows l JOIN legacy_snapshot_rows e "
                          "ON e.table_name='entities' AND e.row_data->>'id'=l.row_data->>'entity_id' "
                          "WHERE l.table_name='entity_links' AND l.row_data->>'doc_id'=d.id::text "
                          f"AND l.row_data->>'link_type'=%s AND e.row_data->>'{field}'=%s)")
                params.extend((link_type, value))
            if days is not None:
                candidates = conn.execute(f'SELECT d.id,d.published_at FROM document_projection d {where}', params).fetchall()
                with closing(sqlite3.connect(':memory:')) as dates:
                    cutoff = dates.execute("SELECT julianday('now', ?)", (f'-{days} days',)).fetchone()[0]
                    eligible = []
                    for ident, published in candidates:
                        value = dates.execute('SELECT julianday(?)', (published,)).fetchone()[0]
                        if value is not None and value >= cutoff:
                            eligible.append(ident)
                where += ' AND d.id=ANY(%s)'
                params.append(eligible)
            total = conn.execute(f'SELECT count(*) FROM document_projection d {where}', params).fetchone()[0]
            if source:
                rows = conn.execute(
                    'SELECT l.list_document FROM document_filter_order o '
                    'JOIN document_list_projection l ON l.ordinal=o.list_ordinal '
                    f'JOIN document_projection d ON d.id=l.document_id {where} '
                    'AND o.filter_key=%s ORDER BY o.position LIMIT %s OFFSET %s',
                    (*params, source, size, (page - 1) * size),
                ).fetchall()
            else:
                rows = conn.execute(
                    f'SELECT l.list_document FROM document_list_projection l '
                    f'JOIN document_projection d ON d.id=l.document_id {where} '
                    'ORDER BY l.ordinal LIMIT %s OFFSET %s',
                    (*params, size, (page - 1) * size),
                ).fetchall()
        return FeedResponse(items=[FeedDocument.model_validate(row[0]) for row in rows],
                            total=total, page=page, size=size,
                            as_of=datetime.now(timezone.utc).isoformat(), facets=None)

    def snapshot_info(self) -> dict | None:
        with self.connection_factory() as conn:
            row = conn.execute(
                'SELECT snapshot_at, document_count, list_row_count, source_observed_at, loaded_at '
                'FROM snapshot_metadata WHERE singleton'
            ).fetchone()
            if row is None:
                return None
            return {'snapshot_at': row[0], 'documents': row[1], 'list_rows': row[2],
                    'source_observed_at': row[3], 'loaded_at': row[4]}
