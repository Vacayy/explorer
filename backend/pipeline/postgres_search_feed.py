"""Fixture-only search feed assembled from a single PostgreSQL generation."""
from datetime import datetime, timezone
from contextlib import closing
import sqlite3

from models.spine import FeedDocument, FeedFacetEntity, FeedFacets, FeedResponse


def _sort_latest(rows):
    # The legacy SQLite IN lookup visits document rowids in ascending order
    # before its stable Python sort by published_at.
    rows.sort(key=lambda row: row[0])
    rows.sort(key=lambda row: row[1].get('published_at') or '', reverse=True)


def search_feed(connection, index, query, *, vector=None, source=None, stock=None,
                industry=None, topic=None, days=None, sort='relevance', page=1, size=20):
    """Return the existing search feed response shape for a fixture generation.

    The caller owns a repeatable-read, read-only transaction. Operation against
    live databases is not supported.
    """
    if page < 1 or not 1 <= size <= 100 or (days is not None and not 1 <= days <= 3650) or sort not in {'relevance', 'latest'}:
        raise ValueError('Invalid page or size')
    if (connection.execute('SHOW transaction_isolation').fetchone()[0] not in ('repeatable read', 'serializable')
            or connection.execute('SHOW transaction_read_only').fetchone()[0] != 'on'):
        raise ValueError('A read-only repeatable-read transaction is required')
    generation = connection.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
    if generation is None or str(generation[0]) != index.generation:
        raise ValueError('Search index generation expired')
    ranking = [result['doc_id'] for result in index.search(query, vector=vector, k=100)]
    as_of = datetime.now(timezone.utc).isoformat()
    if not ranking:
        return FeedResponse(items=[], total=0, page=page, size=size, as_of=as_of, facets=None)
    if source in {'blog', 'news', 'article', 'people'}:
        condition, params = 'd.source_groups @> ARRAY[%s]::text[]', (source,)
    elif source:
        condition, params = 'd.source_type=%s', (source,)
    else:
        condition, params = 'TRUE', ()
    rows = connection.execute(
        'SELECT l.document_id,l.list_document,d.source_type FROM document_list_projection l '
        'JOIN document_projection d ON d.id=l.document_id '
        f'WHERE d.feed_visible AND d.id=ANY(%s) AND {condition} '
        'ORDER BY array_position(%s::bigint[],d.id),l.ordinal',
        (ranking, *params, ranking),
    ).fetchall()
    for link_type, field, value in (('stock', 'aliases', stock), ('industry', 'name', industry), ('topic', 'name', topic)):
        if not value or not rows:
            continue
        matches = connection.execute(
            "SELECT DISTINCT (l.row_data->>'doc_id')::bigint FROM legacy_snapshot_rows l "
            "JOIN legacy_snapshot_rows e ON e.table_name='entities' AND e.row_data->>'id'=l.row_data->>'entity_id' "
            "WHERE l.table_name='entity_links' AND (l.row_data->>'doc_id')::bigint=ANY(%s) "
            f"AND l.row_data->>'link_type'=%s AND e.row_data->>'{field}'=%s",
            (list({row[0] for row in rows}), link_type, value),
        ).fetchall()
        allowed = {row[0] for row in matches}
        rows = [row for row in rows if row[0] in allowed]
    if days is not None and rows:
        # Reuse SQLite's date parser and millisecond rounding from the source;
        # PostgreSQL timestamp parsing does not have identical edge semantics.
        with closing(sqlite3.connect(':memory:')) as dates:
            cutoff = dates.execute("SELECT julianday('now', ?)", (f'-{days} days',)).fetchone()[0]
            def within_window(row):
                parsed = dates.execute('SELECT julianday(?)', (row[1].get('published_at'),)).fetchone()[0]
                return parsed is not None and parsed >= cutoff
            rows = [row for row in rows if within_window(row)]
    if sort == 'latest':
        _sort_latest(rows)
    sources = {}
    for _, _, source_type in rows:
        sources[source_type] = sources.get(source_type, 0) + 1
    ids = list({ident for ident, _, _ in rows})
    entity_rows = []
    if ids:
        entity_rows = connection.execute(
            "SELECT e.row_data->>'name',l.row_data->>'link_type',e.row_data->>'aliases',count(*) AS n "
            "FROM legacy_snapshot_rows l JOIN legacy_snapshot_rows e "
            "ON e.table_name='entities' AND e.row_data->>'id'=l.row_data->>'entity_id' "
            "WHERE l.table_name='entity_links' AND (l.row_data->>'doc_id')::bigint=ANY(%s) "
            "AND l.row_data->>'link_type' IN ('stock','industry','topic') "
            "GROUP BY e.row_data->>'id',e.row_data->>'name',l.row_data->>'link_type',e.row_data->>'aliases' "
            "ORDER BY n DESC,(e.row_data->>'name') COLLATE \"C\" LIMIT 8", (ids,),
        ).fetchall()
    facets = FeedFacets(sources=sources, entities=[FeedFacetEntity(name=n, link_type=t, aliases=a, count=count)
                                                   for n, t, a, count in entity_rows])
    selected = rows[(page - 1) * size:page * size]
    return FeedResponse(items=[FeedDocument.model_validate(row[1]) for row in selected], total=len(rows),
                        page=page, size=size, as_of=as_of, facets=facets)
