"""Read an isolated graph ledger for the existing enrichment prompt."""
from pipeline.postgres_graph_fixture import _guard
from services.tagging_service import INDUSTRY_KEYWORDS, TOPIC_KEYWORDS


def vocabulary_provider(factory):
    """Return a callable; its read transaction ends before model execution."""
    def read():
        with factory() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            _guard(conn)
            if not conn.execute('SELECT 1 FROM ingest_graph_state').fetchone():
                raise ValueError('Graph not initialized')
            if not conn.execute("SELECT 1 FROM legacy_snapshot_tables WHERE table_name='entity_links'").fetchone():
                raise ValueError('Link archive is required')
            rows = conn.execute('''WITH links AS (
                SELECT (l.row_data->>'entity_id')::bigint AS entity_id,
                       l.row_data->>'link_type' AS link_type
                FROM legacy_snapshot_rows l
                LEFT JOIN ingest_documents d ON d.id=(l.row_data->>'doc_id')::bigint
                WHERE l.table_name='entity_links' AND NOT COALESCE(d.links_dirty,FALSE)
                UNION ALL
                SELECT l.entity_id,l.link_type FROM ingest_entity_links l
                JOIN ingest_documents d ON d.id=l.document_id AND d.revision=l.revision
                WHERE d.links_dirty
            )
            SELECT e.id,e.type,e.name,e.aliases,e.status,l.link_type,count(l.entity_id)
            FROM ingest_graph_entities e LEFT JOIN links l ON l.entity_id=e.id
            GROUP BY e.id,e.type,e.name,e.aliases,e.status,l.link_type
            ORDER BY e.id''').fetchall()
        by_entity = {}
        for ident, kind, name, aliases, status, link_type, count in rows:
            entity = by_entity.setdefault(ident, (kind, name, aliases, status, {}))
            entity[4][link_type] = count
        def ranked(kind, link_type, include_unlinked=False):
            found = [(counts.get(link_type, 0) if link_type else sum(counts.values()), ident, name)
                     for ident, (typ, name, aliases, status, counts) in by_entity.items()
                     if typ == kind and (include_unlinked or counts.get(link_type, 0))
                     and (kind != 'company' or (aliases is None and status != 'merged'))]
            return [name for _, _, name in sorted(found, key=lambda r: (-r[0], r[1]))[:40]]
        industries = list(dict.fromkeys([*ranked('sector', 'industry'), *INDUSTRY_KEYWORDS]))
        topics = list(dict.fromkeys([*ranked('theme', 'topic'), *TOPIC_KEYWORDS]))
        return industries, topics, ranked('person', 'person'), ranked('company', None, True)
    return read
