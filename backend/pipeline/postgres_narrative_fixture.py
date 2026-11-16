"""Read existing narrative list from a disposable snapshot."""
import json
from datetime import datetime,timedelta,timezone
from pipeline.postgres_signals_fixture import _guard_read, _require_signals
from pipeline.narrative import _summary, _hash
from routers.spine_narrative import NarrativeList, Narrative


def list_narratives(conn):
    _require_signals(conn)
    metric_rows=conn.execute("""
      SELECT e.row_data->>'name',s.row_data->>'payload_json'
      FROM legacy_snapshot_rows s JOIN legacy_snapshot_rows e
        ON e.table_name='entities' AND e.row_data->>'id'=s.row_data->>'entity_id'
      WHERE s.table_name='signals' AND s.row_data->>'signal_type'='theme_surge'
        AND s.row_data->>'date'=(SELECT max(row_data->>'date') FROM legacy_snapshot_rows
                                 WHERE table_name='signals' AND row_data->>'signal_type'='theme_surge')
      ORDER BY s.row_ordinal
    """).fetchall()
    metrics={name:json.loads(payload) for name,payload in metric_rows}
    # Latest version per topic over every narratives row, in one pass (a per-row subquery
    # is slow once narratives live in the supplement layer).
    rows=conn.execute("""
      SELECT row_data FROM (
        SELECT n.row_data,n.row_ordinal,
               max((n.row_data->>'version')::bigint) OVER (PARTITION BY n.row_data->>'topic') AS latest
        FROM legacy_snapshot_rows n WHERE n.table_name='narratives') n
      WHERE n.row_data->>'title' IS NOT NULL AND COALESCE(n.row_data->>'kind','topic')='topic'
        AND (n.row_data->>'version')::bigint=n.latest
      ORDER BY n.row_ordinal
    """).fetchall()
    items=[]
    for (row,) in rows:
        metric=metrics.get(row['topic'])
        items.append({'topic':row['topic'],'title':row['title'],'summary':_summary(row.get('body')),
            'category':row.get('category'),'share_pct':metric.get('share_pct') if metric else None,
            'share_delta_pp':metric.get('share_delta_pp') if metric else None,
            'is_new':bool(metric.get('is_new')) if metric else False,'is_surging':metric is not None,
            'created_at':row.get('created_at'),'drift_summary':row.get('drift_summary'),'version':row.get('version')})
    surging=sorted((row for row in items if row['is_surging']),key=lambda row:-(row['share_delta_pp'] or 0))
    rest=sorted((row for row in items if not row['is_surging']),key=lambda row:row['created_at'] or '',reverse=True)
    return NarrativeList(items=surging+rest)


def cached_narrative(conn, topic, *, now=None):
    _guard_read(conn)
    instant=now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('Timezone-aware time required')
    cutoff=(instant.astimezone(timezone.utc)-timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
    entity=conn.execute("""
      SELECT e.row_data->>'id' FROM legacy_snapshot_rows e
      WHERE e.table_name='entities' AND e.row_data->>'type' IN ('sector','theme')
        AND e.row_data->>'name'=%s AND e.row_data->>'status' IS DISTINCT FROM 'merged'
      ORDER BY (SELECT count(*) FROM legacy_snapshot_rows l WHERE l.table_name='entity_links'
                AND l.row_data->>'entity_id'=e.row_data->>'id'
                AND l.row_data->>'link_type' IN ('industry','topic')) DESC,(e.row_data->>'id')::bigint
      LIMIT 1
    """,(topic,)).fetchone()
    if entity is None: return Narrative(status='not_found')
    docs=conn.execute("""
      SELECT (d.row_data->>'id')::bigint FROM legacy_snapshot_rows l
      JOIN legacy_snapshot_rows d ON d.table_name='raw_documents' AND d.row_data->>'id'=l.row_data->>'doc_id'
      LEFT JOIN legacy_snapshot_rows e ON e.table_name='enrichments' AND e.row_data->>'doc_id'=d.row_data->>'id'
      WHERE l.table_name='entity_links' AND l.row_data->>'entity_id'=%s
        AND l.row_data->>'link_type' IN ('industry','topic')
        AND (d.row_data->>'published_at') COLLATE "C">=%s AND d.row_data->>'source_type'<>'scrap'
      ORDER BY (d.row_data->>'published_at') COLLATE "C",l.row_ordinal,e.row_ordinal LIMIT 25
    """,(entity[0],cutoff)).fetchall()
    previous=conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='narratives' "
                          "AND row_data->>'topic'=%s ORDER BY (row_data->>'version')::bigint DESC LIMIT 1",(topic,)).fetchone()
    if not previous:
        return Narrative(status='empty',stale=len(docs)>=3)
    row=previous[0]
    return Narrative(status='cached',title=row.get('title'),narrative=row.get('body'),created_at=row.get('created_at'),
                     stale=row.get('doc_ids_hash') != _hash([{'id':doc[0]} for doc in docs]),
                     category=row.get('category'),version=row.get('version'),narrative_id=row.get('id'))
