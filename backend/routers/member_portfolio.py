"""Member ledger routes. Legacy operator routes remain private/unclassified."""
import sqlite3
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from models.member_portfolio import TransactionCreated, TransactionDeleted, CompanyChoice
from models.portfolio import PortfolioSummary, HistoryPoint, TransactionItem, TransactionCreate
from pipeline import portfolio as pf
from security.member_portfolio import MemberPortfolio, TransactionUnavailable

class MemberRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def validated(request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                # Never echo submitted ledger amounts/notes. Nonfinite input
                # also cannot be serialized in Starlette's JSON error body.
                return JSONResponse(status_code=422, content={'detail': [
                    {key: error[key] for key in ('loc', 'type', 'msg')}
                    for error in exc.errors()]})
        return validated


router = APIRouter(prefix='/api/member/portfolio', tags=['member-portfolio'], route_class=MemberRoute)


def member_service(request: Request):
    if not getattr(request.state, 'public_access', False):
        raise HTTPException(404, 'Unavailable')
    user = getattr(request.state, 'principal', None)
    if user is None or not user.enabled or user.role not in {'member', 'operator'}:
        raise HTTPException(401, 'Authentication required')
    from config import DB_PATH
    return MemberPortfolio(DB_PATH, user.id)


def perform(action):
    try:
        return action()
    except TransactionUnavailable:
        raise HTTPException(404, 'Transaction unavailable') from None
    except pf.LedgerError as exc:
        raise HTTPException(409, str(exc)) from None
    except (sqlite3.Error, OSError, ValueError):
        raise HTTPException(503, 'Portfolio unavailable') from None


@router.get('', response_model=PortfolioSummary)
def summary(service: MemberPortfolio = Depends(member_service)):
    return perform(lambda: service.read(pf.summary))


@router.get('/history', response_model=list[HistoryPoint])
def history(service: MemberPortfolio = Depends(member_service)):
    return perform(lambda: service.read(pf.history))


@router.get('/transactions', response_model=list[TransactionItem])
def transactions(service: MemberPortfolio = Depends(member_service)):
    return perform(lambda: service.read(pf.transactions))


@router.post('/transactions', response_model=TransactionCreated)
def add(body: TransactionCreate, service: MemberPortfolio = Depends(member_service)):
    return {'ok': True, 'id': perform(lambda: service.add(body))}


@router.delete('/transactions/{tx_id}', response_model=TransactionDeleted)
def delete(tx_id: int = Path(ge=1), service: MemberPortfolio = Depends(member_service)):
    perform(lambda: service.delete(tx_id))
    return {'ok': True}


@router.get('/companies', response_model=list[CompanyChoice])
def companies(q: str = Query(min_length=1, max_length=80), service: MemberPortfolio = Depends(member_service)):
    return perform(lambda: service.companies(q.strip()))


# Member principles remain separate from the legacy operator scheduler/LLM path.
from models.member_portfolio import MemberPrincipleCreate, PrincipleCreated, PrincipleChanged
from models.portfolio import Principle, PrincipleText
from security.member_principles import MemberPrinciples, PrincipleUnavailable, PrincipleInvalid, PrincipleLimit


def principle_service(service: MemberPortfolio = Depends(member_service)):
    return MemberPrinciples(service.source, service.owner)


def principle_action(action):
    try:
        return perform(action)
    except PrincipleUnavailable:
        raise HTTPException(404, 'Principle unavailable') from None
    except PrincipleInvalid:
        raise HTTPException(422, 'Invalid confirmed principle') from None
    except PrincipleLimit:
        raise HTTPException(409, 'Principle limit reached') from None


@router.get('/principles', response_model=list[Principle])
def principles(service: MemberPrinciples = Depends(principle_service)):
    return principle_action(service.listing)


@router.post('/principles', response_model=PrincipleCreated, status_code=201)
def create_principle(body: MemberPrincipleCreate, service: MemberPrinciples = Depends(principle_service)):
    return {'ok': True, 'id': principle_action(lambda: service.create(body))}


@router.put('/principles/{principle_id}', response_model=PrincipleChanged)
def replace_principle(body: MemberPrincipleCreate, principle_id: int = Path(ge=1),
                      service: MemberPrinciples = Depends(principle_service)):
    principle_action(lambda: service.replace(principle_id, body))
    return {'ok': True}


@router.patch('/principles/{principle_id}', response_model=PrincipleChanged)
def edit_principle_text(body: PrincipleText, principle_id: int = Path(ge=1),
                        service: MemberPrinciples = Depends(principle_service)):
    principle_action(lambda: service.update_text(principle_id, body.text))
    return {'ok': True}


@router.delete('/principles/{principle_id}', response_model=PrincipleChanged)
def delete_principle(principle_id: int = Path(ge=1), service: MemberPrinciples = Depends(principle_service)):
    principle_action(lambda: service.delete(principle_id))
    return {'ok': True}


from models.member_portfolio import MemberPrincipleState


@router.get('/principles/state', response_model=MemberPrincipleState)
def evaluate_principles(service: MemberPrinciples = Depends(principle_service)):
    return principle_action(service.evaluate)


from models.member_portfolio import MemberPrincipleRuleOption
from pipeline import portfolio_principles as principle_rules


@router.get('/principles/rules', response_model=list[MemberPrincipleRuleOption])
def principle_options(service: MemberPrinciples = Depends(principle_service)):
    return [{'type':kind, 'label':meta[0], 'parameter':meta[1], 'minimum':meta[2], 'maximum':meta[3]}
            for kind, meta in principle_rules.RULES.items()]
