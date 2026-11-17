"""Collection buttons on the single-path candidate: recorded, never run.

The candidate does not collect (single writer: the MacBook keeps collecting, and the public IP is
shared). A collection request is kept in `collector_requests` with origin 'candidate' and answered 409
`not_run`, so the screen shows that nothing ran rather than a finished refresh. These rows are not
consumed after cut-over; the cut-over checklist expires them. Wiring the real buttons after cut-over
is separate, still-open work.
"""
import json
import re

from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import _guard

TRIGGERS = (('POST', r'/api/financials/[^/]+/collect'),  # portfolio quotes: routers.postgres_owner_portfolio_fixture
            ('POST', r'/api/spine/macro/snapshot'), ('POST', r'/api/spine/market-regime/snapshot'),
            ('POST', r'/api/spine/regimes/collect'), ('POST', r'/api/spine/risk/snapshot'),
            ('POST', r'/api/spine/sources/refresh'), ('POST', r'/api/spine/trade/seed'),
            ('POST', r'/api/spine/transcript/calendar/refresh'), ('POST', r'/api/spine/transcript/check/[^/]+'),
            ('POST', r'/api/spine/transcript/collect'), ('POST', r'/api/spine/transcript/seed'),
            ('POST', r'/api/spine/tracker/[^/]+/prepare'),  # 30-day flows for a newly tracked stock
            ('POST', r'/api/spine/us/[^/]+/prices/collect'))
MESSAGE = '후보에서는 수집을 실행하지 않습니다. 요청만 기록했고, 운영 전환 뒤에도 자동으로 실행하지 않습니다.'


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('collector_requests')").fetchone()[0] is not None:
            raise ValueError('Collector requests already initialized')
        conn.execute("CREATE TABLE collector_requests (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,kind TEXT NOT NULL,"
                     "params JSONB NOT NULL,origin TEXT NOT NULL CHECK(origin IN ('candidate')),"
                     "status TEXT NOT NULL DEFAULT 'not_run' CHECK(status IN ('not_run','expired')),"
                     'requested_at TIMESTAMPTZ NOT NULL DEFAULT now())')


def install(app, factory):
    patterns = [(method, re.compile(f'^{path}$'), path) for method, path in TRIGGERS]

    @app.middleware('http')
    async def collector_requests(request, call_next):
        match = next(((path, m) for method, pattern, path in patterns
                      if method == request.method and (m := pattern.match(request.url.path))), None)
        if match is None:
            return await call_next(request)
        from starlette.concurrency import run_in_threadpool
        body = await request.body()
        try:
            payload = json.loads(body) if body else None
        except ValueError:
            payload = None
        params = {'path': request.url.path, 'query': dict(request.query_params), 'body': payload}

        def record():
            with factory() as pg:
                return pg.execute("INSERT INTO collector_requests(kind,params,origin) VALUES (%s,%s,'candidate') RETURNING id",
                                  (match[0], Jsonb(params))).fetchone()[0]
        ident = await run_in_threadpool(record)
        return JSONResponse({'detail': MESSAGE, 'status': 'not_run', 'request_id': ident}, status_code=409)
