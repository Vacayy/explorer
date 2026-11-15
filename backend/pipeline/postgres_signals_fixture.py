"""Read-only, disposable experiment for the existing signal list contract."""
import os
import re
import json
from datetime import date,timedelta
from routers.spine_signals import _row_to_item, _RANK_KEY, SummaryTop, SummaryType, SignalsSummary


def signals_items(conn, *, since, signal_type=None):
    database,schema=conn.execute('SELECT current_database(),current_schema()').fetchone()
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or database != 'fixture' or
            not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',schema)):
        raise ValueError('Disposable fixture schema required')
    if (conn.execute('SHOW transaction_isolation').fetchone()[0] != 'repeatable read' or
            conn.execute('SHOW transaction_read_only').fetchone()[0] != 'on'):
        raise ValueError('Read-only repeatable-read required')
    rows=conn.execute("""
      SELECT s.row_data,e.row_data FROM legacy_snapshot_rows s
      JOIN legacy_snapshot_rows e ON e.table_name='entities' AND e.row_data->>'id'=s.row_data->>'entity_id'
      WHERE s.table_name='signals' AND s.row_data->>'date'>=%s
        AND (%s::text IS NULL OR s.row_data->>'signal_type'=%s)
        AND (%s::text IS DISTINCT FROM 'theme_surge' OR s.row_data->>'date'=(
          SELECT max(s2.row_data->>'date') FROM legacy_snapshot_rows s2
          WHERE s2.table_name='signals' AND s2.row_data->>'signal_type'=s.row_data->>'signal_type'
            AND s2.row_data->>'entity_id'=s.row_data->>'entity_id'))
      ORDER BY s.row_data->>'date' DESC,(s.row_data->>'id')::bigint DESC
    """,(since,signal_type,signal_type,signal_type)).fetchall()
    return [_row_to_item({**signal,'entity_name':entity['name'],'stock_code':entity.get('aliases')}) for signal,entity in rows]


def signals_summary(conn, *, days=7):
    # Reuse the same guard before querying any fixture contents.
    signals_items(conn,since='9999-12-31')
    latest=conn.execute("SELECT row_data->>'signal_type',max(row_data->>'date') "
                        "FROM legacy_snapshot_rows WHERE table_name='signals' GROUP BY 1 ORDER BY (row_data->>'signal_type') COLLATE \"C\"").fetchall()
    out=[]
    for kind,day in latest:
        start=(date.fromisoformat(day)-timedelta(days=days-1)).isoformat()
        count=conn.execute("SELECT count(*) FROM legacy_snapshot_rows WHERE table_name='signals' "
                           "AND row_data->>'signal_type'=%s AND row_data->>'date'>=%s AND row_data->>'date'<=%s",(kind,start,day)).fetchone()[0]
        rows=conn.execute("SELECT s.row_data,e.row_data FROM legacy_snapshot_rows s JOIN legacy_snapshot_rows e "
                          "ON e.table_name='entities' AND e.row_data->>'id'=s.row_data->>'entity_id' "
                          "WHERE s.table_name='signals' AND s.row_data->>'signal_type'=%s AND s.row_data->>'date'=%s "
                          "ORDER BY s.row_ordinal",(kind,day)).fetchall()
        ranked=sorted(((json.loads(s.get('payload_json') or '{}'),s,e) for s,e in rows),
                      key=lambda row:-_RANK_KEY.get(kind,lambda _:0)(row[0]))
        out.append(SummaryType(type=kind,latest_date=day,count_latest=len(rows),count_window=count,top=[
            SummaryTop(entity_id=s['entity_id'],name=e['name'],stock_code=e.get('aliases'),ticker=p.get('ticker'))
            for p,s,e in ranked[:3]]))
    out.sort(key=lambda row:(row.latest_date,row.count_latest),reverse=True)
    return SignalsSummary(as_of=max((row.latest_date for row in out),default=None),types=out)
