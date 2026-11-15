"""Compare actual signal list rows in an isolated fixture; prints only counts."""
import os
import sqlite3
import uuid
from datetime import date,datetime,timedelta,timezone
from unittest.mock import patch
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from routers.spine_signals import _row_to_item, signals_summary as sqlite_summary, mention_momentum as sqlite_momentum
from pipeline.postgres_signals_fixture import signals_items, signals_summary as pg_summary, mention_momentum as pg_momentum
from pipeline.postgres_narrative_fixture import list_narratives as pg_narratives, cached_narrative as pg_narrative
from pipeline.narrative import list_narratives as sqlite_narratives, cached_meta as sqlite_narrative
from routers.spine_narrative import NarrativeList, Narrative
from pipeline.postgres_calendar_fixture import calendar_events
from models.spine import CalendarEvent, WatchlistUpdate
from pipeline.postgres_home_fixture import market_highlights, watchlist_updates


def main():
    dsn=os.environ['REFACTOR_POSTGRES_DSN']
    target=psycopg.conninfo.conninfo_to_dict(dsn)
    if (os.environ.get('REFACTOR_TEST_DISPOSABLE'),target.get('host'),target.get('dbname'),target.get('user')) != ('1','pg','fixture','fixture'):
        raise ValueError('Disposable fixture required')
    schema='refactor_fixture_'+uuid.uuid4().hex
    source=sqlite3.connect('file:/data/stock_explorer.db?mode=ro',uri=True)
    source.row_factory=sqlite3.Row
    source.execute('PRAGMA query_only=ON')
    source.execute('BEGIN')
    try:
        latest=source.execute('SELECT max(date) FROM signals').fetchone()[0]
        if not latest: raise ValueError('No signal data')
        since=(date.fromisoformat(latest)-timedelta(days=7)).isoformat()
        signals=[dict(row) for row in source.execute('SELECT * FROM signals')]
        entities=[dict(row) for row in source.execute('SELECT * FROM entities')]
        narratives=[dict(row) for row in source.execute('SELECT * FROM narratives')]
        catalysts=[dict(row) for row in source.execute('SELECT * FROM catalysts')]
        companies=[dict(row) for row in source.execute('SELECT * FROM companies')]
        links=[dict(row) for row in source.execute('SELECT * FROM entity_links')]
        documents=[dict(row) for row in source.execute('SELECT id,published_at,source_type,title,url FROM raw_documents')]
        enrichments=[dict(row) for row in source.execute('SELECT doc_id,time_orientation,reference_period FROM enrichments')]
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('CREATE TABLE {}.legacy_snapshot_rows(table_name text,row_ordinal bigint,row_data jsonb)').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('CREATE TABLE {}.legacy_snapshot_tables(table_name text primary key)').format(sql.Identifier(schema)))
            conn.execute(sql.SQL("INSERT INTO {}.legacy_snapshot_tables VALUES ('signals')").format(sql.Identifier(schema)))
            conn.execute(sql.SQL("INSERT INTO {}.legacy_snapshot_tables VALUES ('catalysts'),('companies')").format(sql.Identifier(schema)))
            conn.execute(sql.SQL("CREATE INDEX ON {}.legacy_snapshot_rows (table_name,(row_data->>'id'))").format(sql.Identifier(schema)))
            conn.execute(sql.SQL("CREATE INDEX ON {}.legacy_snapshot_rows (table_name,(row_data->>'signal_type'),(row_data->>'entity_id'))").format(sql.Identifier(schema)))
            conn.execute(sql.SQL("CREATE INDEX ON {}.legacy_snapshot_rows (table_name,(row_data->>'doc_id'))").format(sql.Identifier(schema)))
            with conn.cursor() as cur:
                for table,rows in [('entities',entities),('signals',signals),('narratives',narratives),('entity_links',links),('raw_documents',documents),('enrichments',enrichments),('catalysts',catalysts),('companies',companies)]:
                    cur.executemany(sql.SQL('INSERT INTO {}.legacy_snapshot_rows VALUES (%s,%s,%s)').format(sql.Identifier(schema)),[(table,i,Jsonb(row)) for i,row in enumerate(rows)])
        counts=[]
        with psycopg.connect(dsn,options=f'-c search_path={schema}') as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            for kind in (None,'theme_surge','mention_surge'):
                where=['s.date >= ?']; params=[since]
                if kind:
                    where.append('s.signal_type = ?');params.append(kind)
                if kind == 'theme_surge':
                    where.append('s.date = (SELECT MAX(s2.date) FROM signals s2 WHERE s2.signal_type=s.signal_type AND s2.entity_id=s.entity_id)')
                rows=source.execute('SELECT s.*,e.name entity_name,e.aliases stock_code FROM signals s JOIN entities e ON e.id=s.entity_id WHERE '+ ' AND '.join(where)+' ORDER BY s.date DESC,s.id DESC',params)
                expected=[_row_to_item(row).model_dump() for row in rows]
                actual=[item.model_dump() for item in signals_items(conn,since=since,signal_type=kind)]
                if actual != expected: raise AssertionError('Signal list mismatch')
                counts.append(len(actual))
            def original_connection():
                connection=sqlite3.connect('file:/data/stock_explorer.db?mode=ro',uri=True)
                connection.row_factory=sqlite3.Row
                connection.execute('PRAGMA query_only=ON')
                return connection
            with patch('routers.spine_signals.get_connection',side_effect=original_connection):
                expected_summary=sqlite_summary(days=7).model_dump()
            if pg_summary(conn,days=7).model_dump() != expected_summary:
                raise AssertionError('Signal summary mismatch')
            with patch('routers.spine_signals.get_connection',side_effect=original_connection):
                expected_momentum=sqlite_momentum(limit=12).model_dump()['items']
            if pg_momentum(conn,limit=12).model_dump()['items'] != expected_momentum:
                raise AssertionError('Momentum mismatch')
            expected_narratives=NarrativeList(items=sqlite_narratives(source)).model_dump()
            actual_narratives=pg_narratives(conn).model_dump()
            if actual_narratives != expected_narratives:
                raise AssertionError('Narrative list mismatch')
            topics=[item['topic'] for item in expected_narratives['items'][:3]]+['fixture-not-found']
            for topic in topics:
                if pg_narrative(conn,topic).model_dump() != Narrative(**sqlite_narrative(source,topic)).model_dump():
                    raise AssertionError('Narrative detail mismatch')
            event_days=[date.fromisoformat(row['event_date']) for row in catalysts]
            start=max(set(event_days),key=lambda day:sum(day<=candidate<=day+timedelta(days=7) for candidate in event_days))
            rows=source.execute('SELECT c.id,c.stock_code,co.corp_name,c.event_type,c.event_date,c.title FROM catalysts c LEFT JOIN companies co ON c.corp_code=co.corp_code WHERE c.event_date>=? AND c.event_date<=? ORDER BY c.event_date ASC',(start.isoformat(),(start+timedelta(days=7)).isoformat())).fetchall()
            watched={row['stock_code'] for row in rows[:2] if row['stock_code']}
            events=sorted([CalendarEvent(**dict(row),in_watchlist=row['stock_code'] in watched) for row in rows],key=lambda e:(not e.in_watchlist,e.event_date))
            if [row.model_dump() for row in calendar_events(conn,start=start,watched_codes=watched)] != [row.model_dump() for row in events]:
                raise AssertionError('Calendar event mismatch')
            since=(date.today()-timedelta(days=7)).isoformat()
            rows=source.execute("SELECT s.*,e.name entity_name,e.aliases stock_code FROM signals s JOIN entities e ON e.id=s.entity_id WHERE s.date>=? ORDER BY s.date DESC,s.id DESC LIMIT 10",(since,))
            expected_highlights=[_row_to_item(row).model_dump() for row in rows]
            if [row.model_dump() for row in market_highlights(conn,today=date.today())] != expected_highlights:
                raise AssertionError('Home highlights mismatch')
            since_dt=(datetime.now(timezone.utc)-timedelta(days=3)).isoformat()
            picked=source.execute("SELECT e.aliases FROM entity_links l JOIN entities e ON e.id=l.entity_id JOIN raw_documents d ON d.id=l.doc_id WHERE l.link_type='stock' AND e.type='company' AND e.aliases IS NOT NULL AND d.published_at>=? LIMIT 1",(since_dt,)).fetchone()
            expected_updates=[]
            if picked:
                code=picked[0]
                docs=source.execute("SELECT DISTINCT d.id doc_id,e.aliases stock_code,e.name corp_name,d.published_at,d.title,d.url,d.source_type FROM entity_links l JOIN entities e ON l.entity_id=e.id JOIN raw_documents d ON l.doc_id=d.id WHERE l.link_type='stock' AND e.type='company' AND e.aliases=? AND d.published_at>=? ORDER BY d.published_at DESC LIMIT 50",(code,since_dt))
                for row in docs:
                    expected_updates.append(WatchlistUpdate(kind='document',doc_id=row['doc_id'],stock_code=row['stock_code'],corp_name=row['corp_name'],occurred_at=row['published_at'],title=row['title'] or '',url=row['url'],source_type=row['source_type'],signal_type=None))
                since_date=(date.today()-timedelta(days=3)).isoformat()
                signal_rows=source.execute("SELECT s.signal_type,s.date,s.payload_json,e.aliases stock_code,e.name corp_name FROM signals s JOIN entities e ON s.entity_id=e.id WHERE e.aliases=? AND s.date>=? ORDER BY s.date DESC LIMIT 20",(code,since_date))
                import json
                for row in signal_rows:
                    payload=json.loads(row['payload_json'] or '{}')
                    expected_updates.append(WatchlistUpdate(kind='signal',stock_code=row['stock_code'],corp_name=row['corp_name'],occurred_at=row['date'],title=f"언급 급증: 최근 7일 {payload.get('count_7d','?')}회",url=None,source_type=None,signal_type=row['signal_type']))
                expected_updates.sort(key=lambda row:row.occurred_at,reverse=True)
                actual_updates=watchlist_updates(conn,watched_codes={code},follow_ids=[],since=since_dt,since_date=since_date)
                if [row.model_dump() for row in actual_updates] != [row.model_dump() for row in expected_updates[:30]]:
                    raise AssertionError('Home updates mismatch')
        print(f'Compared signal lists {counts}, summary, {len(expected_momentum)} momentum, {len(expected_narratives["items"])} narratives, {len(topics)} details, {len(events)} calendar events, {len(expected_highlights)} highlights and {min(len(expected_updates),30)} watched updates: matched')
    finally:
        source.close()
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    main()
