"""Selected home response components for disposable snapshots."""
import json
from datetime import timedelta
from models.spine import WatchlistUpdate
from pipeline.postgres_signals_fixture import signals_items, _require_signals


def market_highlights(conn, *, today):
    return signals_items(conn,since=(today-timedelta(days=7)).isoformat())[:10]


def watchlist_updates(conn, *, watched_codes, follow_ids, since, since_date):
    _require_signals(conn)
    updates=[]
    seen=set()
    if watched_codes:
        rows=conn.execute("""
          SELECT DISTINCT (d.row_data->>'id')::bigint doc_id,e.row_data->>'aliases' stock_code,
                 e.row_data->>'name' corp_name,d.row_data->>'published_at' published_at,
                 d.row_data->>'title' title,d.row_data->>'url' url,d.row_data->>'source_type' source_type
          FROM legacy_snapshot_rows l JOIN legacy_snapshot_rows e
            ON e.table_name='entities' AND e.row_data->>'id'=l.row_data->>'entity_id'
          JOIN legacy_snapshot_rows d ON d.table_name='raw_documents' AND d.row_data->>'id'=l.row_data->>'doc_id'
          WHERE l.table_name='entity_links' AND l.row_data->>'link_type'='stock' AND e.row_data->>'type'='company'
            AND e.row_data->>'aliases'=ANY(%s) AND d.row_data->>'published_at'>=%s
          ORDER BY published_at DESC LIMIT 50
        """,(list(watched_codes),since)).fetchall()
        for ident,code,name,when,title,url,source in rows:
            seen.add(ident)
            updates.append(WatchlistUpdate(kind='document',doc_id=ident,stock_code=code,corp_name=name,
                occurred_at=when,title=title or '',url=url,source_type=source,signal_type=None))
    if follow_ids:
        rows=conn.execute("""
          SELECT DISTINCT (d.row_data->>'id')::bigint doc_id,(e.row_data->>'id')::bigint entity_id,
                 e.row_data->>'type' entity_type,e.row_data->>'name' name,e.row_data->>'aliases' aliases,
                 d.row_data->>'published_at' published_at,d.row_data->>'title' title,
                 d.row_data->>'url' url,d.row_data->>'source_type' source_type
          FROM legacy_snapshot_rows l JOIN legacy_snapshot_rows e
            ON e.table_name='entities' AND e.row_data->>'id'=l.row_data->>'entity_id'
          JOIN legacy_snapshot_rows d ON d.table_name='raw_documents' AND d.row_data->>'id'=l.row_data->>'doc_id'
          WHERE l.table_name='entity_links' AND (l.row_data->>'entity_id')::bigint=ANY(%s)
            AND d.row_data->>'published_at'>=%s ORDER BY published_at DESC LIMIT 50
        """,(list(follow_ids),since)).fetchall()
        for ident,eid,kind,name,code,when,title,url,source in rows:
            if ident in seen: continue
            seen.add(ident)
            updates.append(WatchlistUpdate(kind='document',doc_id=ident,entity_type=kind,entity_id=eid,
                stock_code=code,corp_name=name,occurred_at=when,title=title or '',url=url,source_type=source,signal_type=None))
    if watched_codes:
        rows=conn.execute("""
          SELECT s.row_data,e.row_data FROM legacy_snapshot_rows s JOIN legacy_snapshot_rows e
            ON e.table_name='entities' AND e.row_data->>'id'=s.row_data->>'entity_id'
          WHERE s.table_name='signals' AND e.row_data->>'aliases'=ANY(%s) AND s.row_data->>'date'>=%s
          ORDER BY s.row_data->>'date' DESC LIMIT 20
        """,(list(watched_codes),since_date)).fetchall()
        for signal,entity in rows:
            payload=json.loads(signal.get('payload_json') or '{}')
            updates.append(WatchlistUpdate(kind='signal',stock_code=entity.get('aliases'),corp_name=entity['name'],
                occurred_at=signal['date'],title=f"언급 급증: 최근 7일 {payload.get('count_7d','?')}회",
                url=None,source_type=None,signal_type=signal['signal_type']))
    updates.sort(key=lambda item:item.occurred_at,reverse=True)
    return updates[:30]
