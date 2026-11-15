"""Fixture-only source-lane timeline reader; system lane is not implemented."""
from datetime import datetime, timezone

from models.spine import FeedDocument
from models.timeline import TimelineItem, TimelineResponse
from pipeline.timeline import utc


class PostgreSQLTimelineSources:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def timeline(self, *, source='all', channel=None, topic=None, page=1, size=20, until=None):
        if source not in {'all', 'telegram', 'blog', 'youtube', 'memo'} or not 1 <= page <= 100 or not 1 <= size <= 50:
            raise ValueError('Unsupported source filter or page')
        now = datetime.now(timezone.utc).isoformat()
        until = utc(until) if until else now
        with self.connection_factory() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            rows = conn.execute('''
                SELECT id,document_id,occurred_at,time_label,document
                FROM timeline_source_projection
                WHERE occurred_at <= %s::timestamptz
                  AND (%s = 'all' OR platform = %s)
                  AND (%s::text IS NULL OR channel = %s)
                  AND (%s::text IS NULL OR %s = ANY(topic_names))
                ORDER BY occurred_at DESC,id COLLATE "C" DESC
                LIMIT %s OFFSET %s
            ''', (until, source, source, channel, channel, topic, topic, size+1, (page-1)*size)).fetchall()
        items = []
        for ident, doc_id, stamp, label, payload in rows[:size]:
            doc = FeedDocument.model_validate(payload)
            items.append(TimelineItem(id=ident, kind='source', occurred_at=stamp.isoformat(),
                title=doc.title, subject=doc.channel or doc.source_type,
                time_label=label, to=f'/doc/{doc_id}', document=doc))
        return TimelineResponse(items=items, page=page, size=size,
                                has_more=len(rows)>size, until=until, as_of=now)
