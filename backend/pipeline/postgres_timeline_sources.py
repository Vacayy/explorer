"""Isolated timeline reader over captured SQLite response projections."""
from datetime import datetime, timezone
from uuid import UUID

from models.spine import FeedDocument
from models.timeline import TimelineItem, TimelineResponse, TimelineChannel, TimelineChannelsResponse
from pipeline.timeline import utc


class GenerationExpired(Exception):
    """Requested timeline generation is missing or no longer retained."""


class GenerationTimelineResponse(TimelineResponse):
    generation: str
    archived: bool


def resolve_generation(conn, generation):
    """Resolve within the caller's repeatable-read transaction."""
    row = conn.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
    if not row:
        raise GenerationExpired('No timeline generation available')
    current = row[0]
    requested = UUID(str(generation)) if generation is not None else current
    archived = requested != current
    if archived and not conn.execute('SELECT EXISTS (SELECT 1 FROM archived_timeline_generations WHERE generation_id=%s AND expires_at>clock_timestamp())', (requested,)).fetchone()[0]:
        raise GenerationExpired('Timeline generation expired')
    return requested, archived


class PostgreSQLTimelineSources:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def timeline(self, *, scope='sources', kind='all', source='all', channel=None, topic=None, page=1, size=20, until=None, generation=None):
        if (scope not in {'all', 'sources', 'system'} or
                kind not in {'all', 'company', 'person', 'transcript', 'trade', 'narrative', 'report', 'scenario'} or
                source not in {'all', 'telegram', 'blog', 'youtube', 'memo'} or not 1 <= page <= 100 or not 1 <= size <= 50):
            raise ValueError('Unsupported timeline filter or page')
        now = datetime.now(timezone.utc).isoformat()
        until = utc(until) if until else now
        with self.connection_factory() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            requested, archived = resolve_generation(conn, generation)
            source_table = 'archived_timeline_source' if archived else 'timeline_source_projection'
            system_table = 'archived_timeline_system' if archived else 'timeline_system_projection'
            generation_filter = 'AND generation_id=%s' if archived else ''
            source_generation = (requested,) if archived else ()
            rows = conn.execute(f'''
                SELECT id,document_id,occurred_at,time_label,payload,is_source FROM (
                    SELECT id,document_id,occurred_at,sort_millis,time_label,document AS payload,TRUE AS is_source
                    FROM {source_table}
                    WHERE %s IN ('all','sources') AND %s='all' {generation_filter}
                      AND (%s='all' OR platform=%s)
                      AND (%s::text IS NULL OR channel=%s)
                      AND (%s::text IS NULL OR %s=ANY(topic_names))
                    UNION ALL
                    SELECT id,NULL::bigint,occurred_at,sort_millis,NULL::text,item,FALSE
                    FROM {system_table}
                    WHERE %s IN ('all','system') {generation_filter}
                      AND (%s='all' OR item->>'kind'=%s)
                      AND (%s::text IS NULL OR channel=%s)
                      AND (%s::text IS NULL OR topic=%s)
                ) entries WHERE sort_millis <= FLOOR(EXTRACT(EPOCH FROM %s::timestamptz)*1000 + 0.5)
                ORDER BY sort_millis DESC,id COLLATE "C" DESC LIMIT %s OFFSET %s
            ''', (scope, kind, *source_generation, source, source, channel, channel, topic, topic,
                  scope, *source_generation, kind, kind, channel, channel, topic, topic, until, size+1, (page-1)*size)).fetchall()
        items = []
        for ident, doc_id, stamp, label, payload, is_source in rows[:size]:
            if not is_source:
                items.append(TimelineItem.model_validate(payload))
                continue
            doc = FeedDocument.model_validate(payload)
            items.append(TimelineItem(id=ident, kind='source', occurred_at=stamp.isoformat(),
                title=doc.title, subject=doc.channel or doc.source_type,
                time_label=label, to=f'/doc/{doc_id}', document=doc))
        return GenerationTimelineResponse(items=items, page=page, size=size,
                                has_more=len(rows)>size, until=until, as_of=now, generation=str(requested), archived=archived)

    def channels(self, *, until=None, include_owner_read_state=False, generation=None):
        """Omit the legacy owner's read state unless explicitly requested."""
        from pipeline.connectors.memo import SOURCES as MEMO_SOURCES
        if type(include_owner_read_state) is not bool:
            raise TypeError('include_owner_read_state must be bool')
        until = utc(until) if until else datetime.now(timezone.utc).isoformat()
        with self.connection_factory() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            requested, archived = resolve_generation(conn, generation)
            source_table = 'archived_timeline_source' if archived else 'timeline_source_projection'
            system_table = 'archived_timeline_system' if archived else 'timeline_system_projection'
            legacy_table = 'archived_timeline_legacy' if archived else 'legacy_snapshot_rows'
            generation_filter = 'AND generation_id=%s' if archived else ''
            generation_where = 'WHERE generation_id=%s' if archived else ''
            generation_params = (requested,) if archived else ()
            registries = conn.execute(f"SELECT table_name,row_data FROM {legacy_table} WHERE table_name IN ('telegram_channels','blog_sources','youtube_channels') {generation_filter} ORDER BY row_ordinal", generation_params).fetchall()
            rows = conn.execute(f"""
                WITH updates AS (
                  SELECT id,occurred_at,sort_millis,channel,platform,''::text AS name,preview FROM {source_table} {generation_where}
                  UNION ALL
                  SELECT id,occurred_at,sort_millis,channel,'system'::text,name,preview FROM {system_table} {generation_where}
                ), reads AS (
                  SELECT row_data->>'channel' AS channel, (row_data->>'read_until')::timestamptz AS read_until
                  FROM {legacy_table} WHERE table_name='channel_reads' AND %s {generation_filter}
                ), ranked AS (
                  SELECT u.*, count(*) OVER (PARTITION BY u.channel) AS count,
                    sum(CASE WHEN %s AND u.sort_millis > FLOOR(EXTRACT(EPOCH FROM COALESCE(r.read_until,
                        (SELECT read_until FROM reads WHERE channel='*'), '1970-01-01'::timestamptz))*1000 + 0.5)
                        THEN 1 ELSE 0 END) OVER (PARTITION BY u.channel) AS unread,
                    row_number() OVER (PARTITION BY u.channel ORDER BY u.sort_millis DESC,u.id COLLATE "C" DESC) AS rank
                  FROM updates u LEFT JOIN reads r ON r.channel=u.channel WHERE u.sort_millis <= FLOOR(EXTRACT(EPOCH FROM %s::timestamptz)*1000 + 0.5)
                ) SELECT channel,platform,name,preview,occurred_at,count,unread FROM ranked WHERE rank=1
            """, (*generation_params, *generation_params, include_owner_read_state, *generation_params, include_owner_read_state, until)).fetchall()
        registered = {}
        fields = {'telegram_channels': ('channel_name','display_name','telegram'),
                  'blog_sources': ('url','blog_name','blog'),
                  'youtube_channels': ('channel_id','title','youtube')}
        for table, value in registries:
            if not value.get('is_active'):
                continue
            key_field, name_field, platform = fields[table]
            key = value[key_field]
            ident = f'{platform}:{key}'
            registered[ident] = TimelineChannel(id=ident, name=value[name_field] or key, platform=platform)
        for key, value in MEMO_SOURCES.items():
            ident = f'memo:{key}'
            registered[ident] = TimelineChannel(id=ident, name=value['name'], platform='memo')
        for ident, platform, name, preview, stamp, count, unread in rows:
            registered[ident] = TimelineChannel(id=ident,
                name=registered[ident].name if ident in registered else name or ident,
                platform=platform, count=count, unread=unread or 0,
                latest_at=stamp.isoformat(), preview=preview or '')
        items = sorted(registered.values(), key=lambda item: (item.latest_at or '', item.id), reverse=True)
        return TimelineChannelsResponse(items=items, total=sum(i.count for i in items),
                                        total_unread=sum(i.unread for i in items), until=until)
