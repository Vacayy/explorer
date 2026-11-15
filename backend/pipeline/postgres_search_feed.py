"""Fixture-only search feed assembled from a single PostgreSQL generation."""
from datetime import datetime, timezone

from models.spine import FeedDocument, FeedFacetEntity, FeedFacets, FeedResponse


def search_feed(connection, index, query, *, vector=None, source=None, page=1, size=20):
    """Return the existing feed response shape for a limited source filter.

    The caller owns a repeatable-read, read-only transaction. Entity/date
    filters, latest sort and operation against live databases are not supported.
    """
    if page < 1 or not 1 <= size <= 100:
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
