"""Read existing narrative list from a disposable snapshot."""
import json
from pipeline.postgres_signals_fixture import signals_items
from pipeline.narrative import _summary
from routers.spine_narrative import NarrativeList


def list_narratives(conn):
    signals_items(conn,since='9999-12-31')  # validates disposable, read-only transaction
    if not conn.execute("SELECT 1 FROM legacy_snapshot_tables WHERE table_name='signals'").fetchone():
        raise ValueError('Signal snapshot required')
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
    rows=conn.execute("""
      SELECT n.row_data FROM legacy_snapshot_rows n WHERE n.table_name='narratives'
        AND n.row_data->>'title' IS NOT NULL AND COALESCE(n.row_data->>'kind','topic')='topic'
        AND (n.row_data->>'version')::bigint=(SELECT max((n2.row_data->>'version')::bigint)
          FROM legacy_snapshot_rows n2 WHERE n2.table_name='narratives' AND n2.row_data->>'topic'=n.row_data->>'topic')
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
