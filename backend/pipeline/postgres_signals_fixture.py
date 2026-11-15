"""Read-only, disposable experiment for the existing signal list contract."""
import os
import re
import json
import sqlite3
from datetime import date,datetime,timedelta,timezone
from routers.spine_signals import _row_to_item, _RANK_KEY, SummaryTop, SummaryType, SignalsSummary, MomentumRow, MomentumResponse


def _guard_read(conn):
    database,schema=conn.execute('SELECT current_database(),current_schema()').fetchone()
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or database != 'fixture' or
            not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',schema)):
        raise ValueError('Disposable fixture schema required')
    if (conn.execute('SHOW transaction_isolation').fetchone()[0] != 'repeatable read' or
            conn.execute('SHOW transaction_read_only').fetchone()[0] != 'on'):
        raise ValueError('Read-only repeatable-read required')


def _require_signals(conn):
    _guard_read(conn)
    if not conn.execute("SELECT 1 FROM legacy_snapshot_tables WHERE table_name='signals'").fetchone():
        raise ValueError('Signal snapshot required')


def signals_items(conn, *, since, signal_type=None):
    _require_signals(conn)
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
    _require_signals(conn)
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


def mention_momentum(conn, *, limit=12, now=None, today=None):
    _guard_read(conn)
    instant=now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('Timezone-aware time required')
    instant=instant.astimezone(timezone.utc)
    cutoff7=(instant-timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    cutoff14=(instant-timedelta(days=14)).strftime('%Y-%m-%d %H:%M:%S')
    rows=conn.execute("""
      SELECT e.row_data,l.row_data->>'doc_id',d.row_data->>'published_at'
      FROM legacy_snapshot_rows l
      JOIN legacy_snapshot_rows e ON e.table_name='entities' AND e.row_data->>'id'=l.row_data->>'entity_id'
      JOIN legacy_snapshot_rows d ON d.table_name='raw_documents' AND d.row_data->>'id'=l.row_data->>'doc_id'
      WHERE l.table_name='entity_links' AND l.row_data->>'link_type'='stock'
        AND e.row_data->>'type'='company' AND (d.row_data->>'published_at') COLLATE "C">=%s
      ORDER BY (e.row_data->>'id')::bigint,l.row_ordinal
    """,(cutoff14,)).fetchall()
    grouped={}
    with sqlite3.connect(':memory:') as sqlite:
        for entity,doc_id,published in rows:
            record=grouped.setdefault(entity['id'],{'name':entity['name'],'stock_code':entity.get('aliases'),
                                                    'count_7d':0,'prior_7d':0,'daily':{}})
            if published >= cutoff7: record['count_7d']+=1
            else: record['prior_7d']+=1
            day=sqlite.execute('SELECT date(?)',(published,)).fetchone()[0]
            if day: record['daily'].setdefault(day,set()).add(doc_id)
    days=[((today or date.today())-timedelta(days=i)).isoformat() for i in range(13,-1,-1)]
    scored=[]
    for ident,record in grouped.items():
        count,prior=record['count_7d'],record['prior_7d']
        if count < 2: continue
        scored.append({'entity_id':ident,'name':record['name'],'stock_code':record['stock_code'],
                       'count_7d':count,'prior_7d':prior,'score':round(count/max(prior,1),1),
                       'daily':[len(record['daily'].get(day,())) for day in days]})
    scored.sort(key=lambda row:(-row['count_7d'],-row['score']))
    return MomentumResponse(items=[MomentumRow(rank=i+1,**row) for i,row in enumerate(scored[:limit])],
                            as_of=datetime.now(timezone.utc).isoformat())
