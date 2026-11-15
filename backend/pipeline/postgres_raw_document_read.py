"""Read a document from isolated PostgreSQL legacy rows, not response JSON.

This is an experimental private adapter; it is not registered in the live app.
"""
import json

from models.spine import EntityTag, FeedDocument
from pipeline.sources import source_names_from_rows
from pipeline.youtube_digest import fields_from_job


class PostgreSQLRawDocumentReader:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def get(self, doc_id: int) -> FeedDocument | None:
        with self.connection_factory() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            row = conn.execute(
                "SELECT row_data FROM legacy_snapshot_rows "
                "WHERE table_name='raw_documents' AND row_data->>'id'=%s", (str(doc_id),)
            ).fetchone()
            if row is None:
                return None
            doc = row[0]
            summary = conn.execute(
                "SELECT row_data FROM legacy_snapshot_rows "
                "WHERE table_name='enrichments' AND row_data->>'doc_id'=%s "
                "ORDER BY (row_data->>'enriched_at') COLLATE \"C\" DESC NULLS LAST, "
                "(row_data->>'id')::bigint DESC LIMIT 1", (str(doc_id),)
            ).fetchone()
            enriched = summary[0] if summary else {}
            links = conn.execute(
                "WITH links AS (SELECT row_data, row_ordinal, "
                "row_number() OVER (PARTITION BY row_data->>'entity_id',row_data->>'link_type', "
                "row_data->>'confidence' ORDER BY row_ordinal)-1 AS occurrence "
                "FROM legacy_snapshot_rows WHERE table_name='entity_links' AND row_data->>'doc_id'=%s) "
                "SELECT l.row_data, e.row_data, o.position FROM links l "
                "JOIN legacy_snapshot_rows e ON e.table_name='entities' "
                "AND e.row_data->>'id'=l.row_data->>'entity_id' "
                "LEFT JOIN document_entity_order o ON o.document_id=%s "
                "AND o.entity_id=(l.row_data->>'entity_id')::bigint "
                "AND o.link_type=l.row_data->>'link_type' "
                "AND o.confidence IS NOT DISTINCT FROM (l.row_data->>'confidence')::double precision "
                "AND o.occurrence=l.occurrence ORDER BY o.position NULLS LAST", (str(doc_id), doc_id)
            ).fetchall()
            if any(position is None for _, _, position in links):
                raise ValueError('Missing source entity ordering metadata')
            tags = [EntityTag(entity_id=link['entity_id'], type=entity['type'],
                              name=entity['name'], aliases=entity['aliases'],
                              link_type=link['link_type'], confidence=link['confidence'])
                    for link, entity, _ in links]
            rows = conn.execute(
                "SELECT table_name,row_data FROM legacy_snapshot_rows "
                "WHERE table_name IN ('telegram_channels','blog_sources','youtube_channels','scrap_links') "
                "ORDER BY row_ordinal"
            ).fetchall()
            telegram, blogs, youtube, scraps = {}, [], {}, {}
            for table, value in rows:
                if table == 'telegram_channels':
                    telegram[value['channel_name']] = value['display_name'] or value['channel_name']
                elif table == 'blog_sources':
                    blogs.append((value['url'], value['blog_name'] or value['url']))
                elif table == 'youtube_channels':
                    youtube[value['channel_id']] = value['title']
                elif value['doc_id'] == doc_id and value['channel']:
                    scraps[value['doc_id']] = value['channel']
            blogs.sort(key=lambda item: (item[0] is not None, len(item[0] or '')), reverse=True)
            channel = source_names_from_rows([doc], telegram=telegram, blogs=blogs,
                                             youtube=youtube, scraps=scraps).get(doc_id) or {}
            job = None
            if doc['source_type'] == 'youtube':
                result = conn.execute(
                    "SELECT row_data FROM legacy_snapshot_rows "
                    "WHERE table_name='youtube_digest_jobs' AND row_data->>'doc_id'=%s LIMIT 1",
                    (str(doc_id),),
                ).fetchone()
                job = result[0] if result else None
            return FeedDocument(
                id=doc['id'], source_type=doc['source_type'], title=doc['title'] or '',
                url=doc['url'] or '', published_at=doc['published_at'] or '',
                summary=enriched.get('summary'), channel=channel.get('name'),
                channel_kind=channel.get('kind'), channel_key=channel.get('key'),
                content=doc['markdown'] or doc['raw_content'], **fields_from_job(doc, job),
                images=json.loads(doc['media_json']) if doc['media_json'] else [],
                enrich_model=enriched.get('model'), entities=tags,
            )
