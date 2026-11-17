"""Request counts (api_requests_hourly) and screen usage events (usage_events) on the candidate PG schema.

Same rows as the legacy SQLite observation (pipeline.observe): requests are summed in memory by the unchanged
observe.record_request and added hourly to PG; usage events are inserted as received. Only the admin observe
summary reads these logs and llm_calls: its connection gets TEMP copies of the requested window
(observe_connection), so ordinary reads never carry them.
"""
from pipeline.postgres_graph_fixture import _guard

USAGE_COLUMNS = ('ts', 'session', 'type', 'name', 'ref', 'entity', 'dwell_ms', 'section', 'tab')
REQUEST_COLUMNS = ('hour', 'method', 'route', 'status_class', 'count', 'total_ms', 'max_ms', 'b100', 'b300', 'b1000', 'b3000', 'bslow')
LLM_COLUMNS = ('id', 'job', 'model', 'engine', 'effort', 'input_tokens', 'cache_create_tokens', 'cache_read_tokens',
               'output_tokens', 'thinking_tokens', 'cost_usd', 'duration_ms', 'ok', 'error', 'created_at')


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        conn.execute('CREATE TABLE IF NOT EXISTS api_requests_hourly (hour TEXT NOT NULL,method TEXT NOT NULL,route TEXT NOT NULL,'
                     'status_class TEXT NOT NULL,count INTEGER DEFAULT 0,total_ms DOUBLE PRECISION DEFAULT 0,'
                     'max_ms DOUBLE PRECISION DEFAULT 0,b100 INTEGER DEFAULT 0,b300 INTEGER DEFAULT 0,b1000 INTEGER DEFAULT 0,'
                     'b3000 INTEGER DEFAULT 0,bslow INTEGER DEFAULT 0,PRIMARY KEY (hour,method,route,status_class))')
        conn.execute('CREATE TABLE IF NOT EXISTS usage_events (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,ts TEXT NOT NULL,'
                     'session TEXT,type TEXT NOT NULL,name TEXT NOT NULL,ref TEXT,entity TEXT,dwell_ms INTEGER,section TEXT,tab TEXT)')
        conn.execute('CREATE INDEX IF NOT EXISTS usage_events_ts ON usage_events(ts)')


def flush(factory):
    """observe.flush on PG: add the in-memory request counts; on failure they are put back for the next time."""
    from pipeline import observe
    with observe._lock:
        buf, observe._buf = observe._buf, {}
    if not buf:
        return 0
    try:
        with factory() as conn:
            for (hour, method, route, status_class), b in buf.items():
                conn.execute(f'INSERT INTO api_requests_hourly ({",".join(REQUEST_COLUMNS)}) VALUES ({",".join(["%s"] * 12)}) '
                             'ON CONFLICT (hour,method,route,status_class) DO UPDATE SET count=api_requests_hourly.count+excluded.count,'
                             'total_ms=api_requests_hourly.total_ms+excluded.total_ms,max_ms=GREATEST(api_requests_hourly.max_ms,excluded.max_ms),'
                             'b100=api_requests_hourly.b100+excluded.b100,b300=api_requests_hourly.b300+excluded.b300,'
                             'b1000=api_requests_hourly.b1000+excluded.b1000,b3000=api_requests_hourly.b3000+excluded.b3000,'
                             'bslow=api_requests_hourly.bslow+excluded.bslow',
                             (hour, method, route, status_class, b['count'], b['total_ms'], b['max_ms'],
                              b['b100'], b['b300'], b['b1000'], b['b3000'], b['bslow']))
        return len(buf)
    except Exception as exc:  # noqa: BLE001 - observation never blocks a request; retried next time
        with observe._lock:
            for key, b in buf.items():
                current = observe._buf.setdefault(key, {k: 0 for k in b})
                for k, v in b.items():
                    current[k] = max(current[k], v) if k == 'max_ms' else current[k] + v
        print(f'[observe] request counts not saved (retried next time): {type(exc).__name__}')
        return 0


def save_events(factory, events):
    """observe.save_events on PG (same filtering and truncation)."""
    from pipeline.observe import EVENT_TYPES
    rows = [(e['ts'], e.get('session'), e['type'], e['name'][:200], (e.get('ref') or None) and e['ref'][:200],
             (e.get('entity') or None) and str(e['entity'])[:100], e.get('dwell_ms'),
             (e.get('section') or None) and e['section'][:40], (e.get('tab') or None) and e['tab'][:40])
            for e in events if e.get('type') in EVENT_TYPES and e.get('name')]
    if rows:
        with factory() as conn:
            conn.cursor().executemany(f'INSERT INTO usage_events ({",".join(USAGE_COLUMNS)}) VALUES ({",".join(["%s"] * 9)})', rows)
    return len(rows)


def ready(conn):
    return all(conn.execute('SELECT to_regclass(%s)', (t,)).fetchone()[0] is not None
               for t in ('api_requests_hourly', 'usage_events', 'llm_calls', 'client_errors'))


def observe_connection(projection, factory, days):
    """A projection read connection with TEMP copies of the observation logs for `days` (and the previous period
    the summary compares with)."""
    window = f"{2 * days + 2} days"
    conn = projection.connect()
    conn.execute('PRAGMA query_only=OFF')  # TEMP tables only: the file itself is opened read-only
    with factory() as pg:
        for table, columns, where, params in (
                ('llm_calls', LLM_COLUMNS, "created_at >= to_char(timezone('utc',now()) - %s::interval,'YYYY-MM-DD HH24:MI:SS')", (window,)),
                ('api_requests_hourly', REQUEST_COLUMNS, "hour >= to_char(timezone('utc',now()) - %s::interval,'YYYY-MM-DD HH24:00')", (window,)),
                ('usage_events', USAGE_COLUMNS, "ts >= to_char(timezone('utc',now()) - %s::interval,'YYYY-MM-DD\"T\"HH24:MI:SS')", (window,))):
            conn.execute(f'CREATE TEMP TABLE IF NOT EXISTS "{table}" ({",".join(columns)})')
            conn.execute(f'DELETE FROM temp."{table}"')
            conn.executemany(f'INSERT INTO temp."{table}" ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
                             pg.execute(f'SELECT {",".join(columns)} FROM {table} WHERE {where}', params).fetchall())
    conn.commit()
    conn.execute('PRAGMA query_only=ON')
    return conn
