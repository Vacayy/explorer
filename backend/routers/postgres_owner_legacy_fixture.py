"""Unchanged legacy group writes over writable TEMP copies, kept in the owner ledger.

Loopback-only preview adapter, minimal scope: create/rename/delete a group and
add/update/remove its members, replace its rules and toggle member tracking. Each request borrows one projection connection
whose owner tables are TEMP copies of the PG ledger; the legacy handler runs
unchanged on it and, only if it ends 2xx, the PK diff is stored in one PG
transaction that first checks no other write landed. Writes to any other table
hit the read-only projection and fail the request (fail closed). Evaluation,
tracker preparation and reasons (model call) stay unavailable here.
"""
import re

from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from pipeline import postgres_owner_legacy_fixture as owner_legacy
from pipeline.postgres_legacy_projection import write_connection_var

ADAPTED = (('POST', '/api/spine/groups'), ('PATCH', '/api/spine/groups/{group_id}'),
           ('DELETE', '/api/spine/groups/{group_id}'), ('POST', '/api/spine/groups/{group_id}/members'),
           ('PATCH', '/api/spine/groups/{group_id}/members/{stock_code}'),
           ('DELETE', '/api/spine/groups/{group_id}/members/{stock_code}'),
           ('PUT', '/api/spine/groups/{group_id}/rules'),
           ('PUT', '/api/spine/groups/{group_id}/members/{stock_code}/tracked'))
LOCK = 'owner-legacy-write'


class _Borrowed:
    """The request's connection; legacy code may close it, the adapter keeps it."""
    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass

    def __enter__(self):
        return self._conn.__enter__()

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _rows(conn):
    return {table: {row['id']: dict(row) for row in conn.execute(f'SELECT * FROM temp."{table}"')}
            for table in owner_legacy.TABLES}


def _diff(before, after, group):
    changes = []
    for table in owner_legacy.TABLES:
        old, new = before[table], after[table]
        upserts = {pk: row for pk, row in new.items() if old.get(pk) != row}
        deletes = [pk for pk in old if pk not in new]
        if table == 'stock_group_members':
            touched = [*upserts.values(), *(old[pk] for pk in deletes), *(old[pk] for pk in upserts if pk in old)]
            if any(row.get('group_id') == group for row in touched):
                raise PermissionError('Portfolio members are kept by the portfolio ledger')
        changes.append((table, upserts, deletes))
    return changes


def install(app, projection, factory):
    from routers import spine_groups
    wanted = set(ADAPTED)
    for route in spine_groups.router.routes:
        if isinstance(route, APIRoute) and any((method, route.path) in wanted for method in route.methods):
            app.router.routes.append(route)
    patterns = [(method, re.compile('^' + re.sub(r'\\\{[^}]+\\\}', '[^/]+', re.escape(path)) + '$')) for method, path in ADAPTED]

    @app.middleware('http')
    async def legacy_group_writes(request, call_next):
        if not any(method == request.method and pattern.match(request.url.path) for method, pattern in patterns):
            return await call_next(request)
        from starlette.concurrency import run_in_threadpool
        conn, started = await run_in_threadpool(projection.write_connection)
        try:
            before = _rows(conn)
            token = write_connection_var.set(_Borrowed(conn))
            try:
                response = await call_next(request)
            finally:
                write_connection_var.reset(token)
            if not 200 <= response.status_code < 300:
                return response  # TEMP changes are discarded with the connection

            def store():
                with factory() as pg:
                    pg.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (LOCK,))
                    changes = _diff(before, _rows(conn), owner_legacy.portfolio_group(pg))
                    sequences = dict(conn.execute('SELECT name,seq FROM temp.sqlite_sequence'))
                    owner_legacy.apply(pg, started, changes, {t: s for t, s in sequences.items() if t in owner_legacy.TABLES})
            try:
                await run_in_threadpool(store)
            except (RuntimeError, PermissionError) as exc:
                return JSONResponse({'detail': str(exc)}, status_code=409)
            return response
        finally:
            conn.close()
