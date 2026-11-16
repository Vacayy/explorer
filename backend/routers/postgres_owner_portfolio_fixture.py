"""Loopback-only owner portfolio writes on the PG ledger for the single-path preview.

The preview has no authentication: the owner is whichever principal the data
explicitly maps to the archived owner group (one `fixture_portfolio_legacy_mapping`
row); nothing is hard-coded or inferred, so a production cut-over remaps data. Never serve this router beyond the
private loopback gateway; external exposure needs the member/owner gate first.
Responses keep the legacy owner routes' shapes and errors. Quote refresh stays unavailable; principle
parsing and holding theses (native question creation with the stock code, as the watch reasons) call models.
"""
import json

from fastapi import APIRouter, HTTPException
from fastapi.routing import APIRoute

from models.portfolio import (HistoryPoint, Principle, PrincipleCreate, PrincipleParse, PrincipleParseRequest, PrincipleText, PortfolioSummary,
                              ThesisCreate, TransactionCreate, TransactionItem)
from pipeline import portfolio_principles as pp
from pipeline import postgres_portfolio_fixture as ledger
from pipeline.portfolio import LedgerError

def _rules(body):
    clean = pp.validate([rule.model_dump(exclude={'summary'}) for rule in body.rules])
    notes = pp._clean_notes(body.notes)
    if not clean and not notes:
        raise ValueError('점검 규칙이나 참고 원칙이 하나는 있어야 합니다.')
    return json.dumps(clean), json.dumps(notes, ensure_ascii=False)


def create_router(factory, *, run_llm=None, search=None):
    router = APIRouter(prefix='/api/portfolio')

    def owner(conn, create=False):
        from pipeline.postgres_principals import PrincipalRequired, owner_account
        try:
            return owner_account(conn, create=create)  # the request principal's ledger (the operator's without one)
        except PrincipalRequired as exc:
            raise HTTPException(401, 'Authentication required') from exc
        except LookupError as exc:
            raise HTTPException(503, 'Owner portfolio ledger unavailable') from exc

    def account(conn, create=False):
        return owner(conn, create)[0]

    def read():
        with factory() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            principal = owner(conn)[1]
            market = ledger.FixturePortfolioMarket(conn, captured_quotes=True)
            return ledger.read_portfolio(conn, principal, names=market.names(), prices=market.prices)

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
            principal = owner(conn)[1]
            market = ledger.FixturePortfolioMarket(conn)
            try:
                ident = ledger.add_transaction(conn, principal, body.model_dump(), companies=set(market.names()),
                                               last_close=market.last_close)
            except LedgerError as exc:
                conn.rollback()
                raise HTTPException(409, str(exc)) from exc
        return {'ok': True, 'id': ident}

    @router.delete('/transactions/{tx_id}')
    def remove_transaction(tx_id: int):
        with factory() as conn:
            principal = owner(conn)[1]
            try:
                ledger.delete_transaction(conn, principal, tx_id)  # a missing id is not an error, as before
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

    @router.post('/principles/parse', response_model=PrincipleParse)
    def parse_principle(body: PrincipleParseRequest):
        # The legacy preview: one model call, nothing stored, the ledger is not sent to the model. The legacy
        # call goes to the Claude CLI only; here the same system prompt, context and schema go through llm.run
        # (registered task, Codex fallback when Claude is unavailable).
        def call(system, context, schema):
            import re
            from pipeline import llm
            text = llm.run(json.dumps(context, ensure_ascii=False), task='portfolio.principle_parse', system=system,
                           json_schema=schema, record_call=lambda *args: None).text
            match = re.search(r'\{.*\}', text, re.S)
            return json.loads(match.group(0) if match else text)
        try:
            return pp.parse(body.text, call=call)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, f'원칙을 해석하지 못했습니다: {type(e).__name__}')

    @router.post('/thesis', status_code=201)
    def create_thesis(body: ThesisCreate):
        # Legacy portfolio_thesis.start: the thesis becomes a tracked question tied to the holding.
        from pipeline import portfolio_thesis as pt
        from pipeline.postgres_question_orchestration_fixture import (QuestionModelUncertain, QuestionRunUnresolved,
                                                                      create_question_native)
        held = {h['code']: h['name'] for h in read()['summary']['holdings']}
        if body.stock_code not in held:
            raise HTTPException(404, '보유 종목이 아닙니다.')
        if run_llm is None or search is None:
            raise HTTPException(503, '질문 생성이 준비되지 않았습니다')
        name = held[body.stock_code]
        try:
            result = create_question_native(factory, pt.question_text(name, body.why, body.falsifier), run_llm=run_llm,
                                            search=search, created_by='portfolio', stock_code=body.stock_code,
                                            hint=pt.KR_HINT.format(name=name, code=body.stock_code))
        except QuestionRunUnresolved as exc:
            raise HTTPException(409, {'message': str(exc), 'run_id': exc.run_id}) from exc
        except (QuestionModelUncertain, ValueError) as exc:
            raise HTTPException(503, '논지를 질문으로 분해하지 못했습니다') from exc
        return {'id': result['question_id']}

    @router.post('/principles', status_code=201)
    def create_principle(body: PrincipleCreate):
        try:
            rules, notes = _rules(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with factory() as conn:
            ident = conn.execute('INSERT INTO fixture_portfolio_principles(account_id,text,rules_json,notes_json) '
                                 'VALUES (%s,%s,%s,%s) RETURNING id', (account(conn, True), body.text.strip(), rules, notes)).fetchone()[0]
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


def install(app, factory, *, run_llm=None, search=None):
    """Put the ledger routes ahead of any read-only portfolio route with the same path."""
    router = create_router(factory, run_llm=run_llm, search=search)
    owned = {(route.path, method) for route in router.routes for method in route.methods}
    app.router.routes[:] = [route for route in app.router.routes
                            if not (isinstance(route, APIRoute) and any((route.path, m) in owned for m in route.methods))]
    app.include_router(router)
