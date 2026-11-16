"""Loopback-only owner portfolio writes on the PG ledger for the single-path preview.

The preview has no authentication: the principal is the one explicitly mapped
to the archived owner group and is fixed here. Never serve this router beyond the
private loopback gateway; external exposure needs the member/owner gate first.
Responses keep the legacy owner routes' shapes and errors. Quote refresh,
principle parsing (model call) and thesis writes stay unavailable.
"""
import json

from fastapi import APIRouter, HTTPException
from fastapi.routing import APIRoute

from models.portfolio import (HistoryPoint, Principle, PrincipleCreate, PrincipleText, PortfolioSummary,
                              TransactionCreate, TransactionItem)
from pipeline import portfolio_principles as pp
from pipeline import postgres_portfolio_fixture as ledger
from pipeline.portfolio import LedgerError

OWNER = 'local-preview-owner'


def _rules(body):
    clean = pp.validate([rule.model_dump(exclude={'summary'}) for rule in body.rules])
    notes = pp._clean_notes(body.notes)
    if not clean and not notes:
        raise ValueError('점검 규칙이나 참고 원칙이 하나는 있어야 합니다.')
    return json.dumps(clean), json.dumps(notes, ensure_ascii=False)


def create_router(factory):
    router = APIRouter(prefix='/api/portfolio')

    def account(conn):
        ident = ledger._account(conn, OWNER, lock=False)
        if ident is None:
            raise HTTPException(503, 'Owner portfolio ledger unavailable')
        return ident

    def read():
        with factory() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            account(conn)
            market = ledger.FixturePortfolioMarket(conn, captured_quotes=True)
            return ledger.read_portfolio(conn, OWNER, names=market.names(), prices=market.prices)

    @router.get('', response_model=PortfolioSummary)
    def summary():
        return read()['summary']

    @router.get('/history', response_model=list[HistoryPoint])
    def history():
        return read()['history']

    @router.get('/transactions', response_model=list[TransactionItem])
    def transactions():
        return read()['transactions']

    @router.post('/transactions')
    def create_transaction(body: TransactionCreate):
        with factory() as conn:
            account(conn)
            market = ledger.FixturePortfolioMarket(conn)
            try:
                ident = ledger.add_transaction(conn, OWNER, body.model_dump(), companies=set(market.names()),
                                               last_close=market.last_close)
            except LedgerError as exc:
                conn.rollback()
                raise HTTPException(409, str(exc)) from exc
        return {'ok': True, 'id': ident}

    @router.delete('/transactions/{tx_id}')
    def remove_transaction(tx_id: int):
        with factory() as conn:
            account(conn)
            try:
                ledger.delete_transaction(conn, OWNER, tx_id)  # a missing id is not an error, as before
            except LedgerError as exc:
                conn.rollback()
                raise HTTPException(409, str(exc)) from exc
        return {'ok': True}

    @router.get('/principles', response_model=list[Principle])
    def list_principles():
        with factory() as conn:
            rows = conn.execute('SELECT id,text,created_at,rules_json,notes_json FROM fixture_portfolio_principles '
                                'WHERE account_id=%s ORDER BY id', (account(conn),)).fetchall()
        return [{'id': ident, 'text': text, 'created_at': created,
                 'rules': [{**rule, 'summary': pp.describe(rule)} for rule in json.loads(rules)],
                 'notes': json.loads(notes) if notes else []} for ident, text, created, rules, notes in rows]

    @router.post('/principles', status_code=201)
    def create_principle(body: PrincipleCreate):
        try:
            rules, notes = _rules(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with factory() as conn:
            ident = conn.execute('INSERT INTO fixture_portfolio_principles(account_id,text,rules_json,notes_json) '
                                 'VALUES (%s,%s,%s,%s) RETURNING id', (account(conn), body.text.strip(), rules, notes)).fetchone()[0]
        return {'id': ident}

    def change(sql, params, principle_id):
        with factory() as conn:
            if not conn.execute(sql, (*params, principle_id, account(conn))).rowcount:
                raise HTTPException(404, '원칙을 찾을 수 없습니다.')

    @router.patch('/principles/{principle_id}')
    def update_principle_text(principle_id: int, body: PrincipleText):
        change('UPDATE fixture_portfolio_principles SET text=%s WHERE id=%s AND account_id=%s', (body.text.strip(),), principle_id)
        return {'ok': True}

    @router.put('/principles/{principle_id}')
    def replace_principle(principle_id: int, body: PrincipleCreate):
        try:
            rules, notes = _rules(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        change('UPDATE fixture_portfolio_principles SET text=%s,rules_json=%s,notes_json=%s WHERE id=%s AND account_id=%s',
               (body.text.strip(), rules, notes), principle_id)
        return {'ok': True}

    @router.delete('/principles/{principle_id}')
    def delete_principle(principle_id: int):
        with factory() as conn:
            conn.execute('DELETE FROM fixture_portfolio_principles WHERE id=%s AND account_id=%s', (principle_id, account(conn)))
        return {'ok': True}

    return router


def install(app, factory):
    """Put the ledger routes ahead of any read-only portfolio route with the same path."""
    router = create_router(factory)
    owned = {(route.path, method) for route in router.routes for method in route.methods}
    app.router.routes[:] = [route for route in app.router.routes
                            if not (isinstance(route, APIRoute) and any((route.path, m) in owned for m in route.methods))]
    app.include_router(router)
