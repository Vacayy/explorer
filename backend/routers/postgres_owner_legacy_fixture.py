"""Unchanged legacy group writes over writable TEMP copies, kept in the owner ledger.

Loopback-only preview adapter, minimal scope: create/rename/delete a group and
add/update/remove its members, replace its rules and toggle member tracking; add industry
universe members, edit business segments and IR notes. Each request borrows one projection connection
whose owner tables are TEMP copies of the PG ledger; the legacy handler runs
unchanged on it and, only if it ends 2xx, the PK diff is stored in one PG
transaction that first checks no other write landed. Writes to any other table
hit the read-only projection and fail the request (fail closed). Evaluation and
tracker preparation stay unavailable; watch reasons use the native question gate.
"""
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from pipeline import postgres_owner_legacy_fixture as owner_legacy
from pipeline.postgres_legacy_projection import write_connection_var

ADAPTED = (('POST', '/api/spine/groups'), ('PATCH', '/api/spine/groups/{group_id}'),
           ('DELETE', '/api/spine/groups/{group_id}'), ('POST', '/api/spine/groups/{group_id}/members'),
           ('PATCH', '/api/spine/groups/{group_id}/members/{stock_code}'),
           ('DELETE', '/api/spine/groups/{group_id}/members/{stock_code}'),
           ('PUT', '/api/spine/groups/{group_id}/rules'),
           ('PUT', '/api/spine/groups/{group_id}/members/{stock_code}/tracked'),
           ('POST', '/api/industries/{group_id}/members'), ('POST', '/api/business/{stock_code}/segments'),
           ('PUT', '/api/business/segments/{segment_id}'), ('DELETE', '/api/business/segments/{segment_id}'),
           ('POST', '/api/ir-notes/{stock_code}'), ('DELETE', '/api/ir-notes/{note_id}'))
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


def _reasons_router(projection, factory, run_llm, search):
    """Watch reasons: the legacy checks on the projection, then the native question gate."""
    from models.groups import ReasonCreate
    from pipeline import portfolio_thesis as pt
    from pipeline import watch_reasons as wrs
    from routers.spine_groups import _group
    router = APIRouter()

    @router.post('/api/spine/groups/{group_id}/reasons', status_code=201)
    def create_reason(group_id: int, body: ReasonCreate, request: Request):
        from pipeline.postgres_question_orchestration_fixture import (QuestionModelUncertain, QuestionRunUnresolved,
                                                                      create_question_native)
        conn = projection.connect()
        try:
            group = _group(conn, group_id)
            if group['kind'] != 'watch':
                raise HTTPException(409, '관심 묶음에서만 이유를 감시합니다. 보유 종목은 포트폴리오의 ‘보유 논지’를 쓰세요.')
            row = conn.execute('''SELECT c.corp_name FROM stock_group_members m LEFT JOIN companies c ON c.stock_code = m.stock_code
                                  WHERE m.group_id=? AND m.stock_code=?''', (group_id, body.stock_code)).fetchone()
            if not row:
                raise HTTPException(404, '이 묶음의 종목이 아닙니다.')
            name = row['corp_name'] or body.stock_code
        finally:
            conn.close()
        if run_llm is None or search is None:
            raise HTTPException(503, '질문 생성이 준비되지 않았습니다')
        # Same optional fixture cap as question creation, for deliberate representative tests only.
        limit = request.headers.get('x-explorer-fixture-model-limit')
        if limit is not None and (not limit.isdigit() or not 1 <= int(limit) <= 4):
            raise HTTPException(400, '시험 호출 제한이 올바르지 않습니다')
        calls = 0

        def model(prompt, *, task):
            nonlocal calls
            if limit is not None and calls >= int(limit):
                raise RuntimeError('fixture model call limit reached')
            calls += 1
            return run_llm(prompt, task=task)
        hint = pt.KR_HINT.format(name=name, code=body.stock_code).replace('보유 종목', '관심 종목')
        try:
            result = create_question_native(factory, wrs.question_text(name, body.why, body.trigger), run_llm=model,
                                            search=search, created_by=wrs.CREATOR, stock_code=body.stock_code, hint=hint,
                                            numeric_limit=1 if limit is not None else 40)
        except QuestionRunUnresolved as exc:
            raise HTTPException(409, {'message': str(exc), 'run_id': exc.run_id}) from exc
        except (QuestionModelUncertain, ValueError) as exc:
            raise HTTPException(503, '이유를 질문으로 분해하지 못했습니다') from exc
        return {'id': result['question_id']}

    return router


def install(app, projection, factory, *, run_llm=None, search=None):
    app.include_router(_reasons_router(projection, factory, run_llm, search))
    from routers import business, industries, ir_notes, spine_groups
    wanted = set(ADAPTED)
    for router in (spine_groups.router, industries.router, business.router, ir_notes.router):
        for route in router.routes:
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
