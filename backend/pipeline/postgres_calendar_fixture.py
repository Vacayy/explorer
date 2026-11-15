"""Home calendar reads from disposable snapshots; no external collection."""
from datetime import timedelta
from models.spine import CalendarEvent
from pipeline.postgres_signals_fixture import signals_items


def calendar_events(conn, *, start, watched_codes):
    signals_items(conn,since='9999-12-31')
    present={row[0] for row in conn.execute("SELECT table_name FROM legacy_snapshot_tables WHERE table_name IN ('catalysts','companies')")}
    if present != {'catalysts','companies'}: raise ValueError('Event snapshot required')
    rows=conn.execute("""
        SELECT c.row_data,co.row_data->>'corp_name'
        FROM legacy_snapshot_rows c LEFT JOIN legacy_snapshot_rows co
          ON co.table_name='companies' AND co.row_data->>'corp_code'=c.row_data->>'corp_code'
        WHERE c.table_name='catalysts' AND c.row_data->>'event_date'>=%s AND c.row_data->>'event_date'<=%s
        ORDER BY c.row_data->>'event_date',c.row_ordinal
    """,(start.isoformat(),(start+timedelta(days=7)).isoformat())).fetchall()
    events=[CalendarEvent(id=row['id'],stock_code=row.get('stock_code'),corp_name=name,event_type=row['event_type'],
                          event_date=row['event_date'],title=row['title'],in_watchlist=row.get('stock_code') in watched_codes)
            for row,name in rows]
    events.sort(key=lambda event:(not event.in_watchlist,event.event_date))
    return events
