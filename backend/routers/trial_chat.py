"""Bounded anonymous chat requests; transcript data stays in request memory."""
import hmac
import sqlite3
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse

from models.trial_chat import TrialAnswer, TrialQuestion, TrialSession
from security.access_boundary import NO_STORE
from security.public_evidence import EvidenceChanged, EvidenceUnavailable, InvalidAnswer
from security.trial_chat import IncompleteExecution
from security.trial_identity import COOKIE_NAME, COOKIE_TTL, InvalidTrialIdentity
from security.trial_quota import QuotaExceeded
from security.trial_service import TrialService

BODY_LIMIT = 96 * 1024


class TrialRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def bounded(request):
            if request.method == 'POST':
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > BODY_LIMIT:
                        return JSONResponse({'detail': 'Request too large'}, status_code=413, headers=NO_STORE)
                    chunks.append(chunk)
                request._body = b''.join(chunks)
            try:
                return await original(request)
            except (RequestValidationError, UnicodeError):
                return JSONResponse({'detail': 'Invalid chat request'}, status_code=422, headers=NO_STORE)
        return bounded


router = APIRouter(tags=['trial-chat'], route_class=TrialRoute)


def trial_service(request: Request):
    if not getattr(request.state, 'public_access', False):
        raise HTTPException(404, 'Chat unavailable', headers=NO_STORE)
    try:
        return TrialService.from_environment()
    except (KeyError, ValueError, OSError, sqlite3.Error):
        raise HTTPException(503, 'Chat unavailable', headers=NO_STORE) from None


def check_origin(request, identity, write=False):
    if not identity.valid_origin(request.headers.get('origin'), request.headers.get('sec-fetch-site'), write):
        raise HTTPException(403, 'Request rejected', headers=NO_STORE)


@router.get('/api/public/chat/session', response_model=TrialSession)
def session(request: Request, response: Response, service=Depends(trial_service)):
    check_origin(request, service.identity)
    cookie = request.cookies.get(COOKIE_NAME)
    try:
        actor = service.identity.actor_hash(cookie)
    except InvalidTrialIdentity:
        cookie = service.identity.issue_cookie()
        actor = service.identity.actor_hash(cookie)
        response.set_cookie(COOKIE_NAME, cookie, max_age=COOKIE_TTL, secure=True,
                            httponly=True, samesite='lax', path='/')
    try:
        remaining = service.quota.remaining(actor)
    except (sqlite3.Error, OSError):
        raise HTTPException(503, 'Chat unavailable', headers=NO_STORE) from None
    response.headers.update(NO_STORE)
    return {'remaining': remaining, 'limit': service.quota.policy.per_actor_limit,
            'csrf_token': service.identity.csrf(cookie)}


@router.post('/api/public/chat', response_model=TrialAnswer)
async def chat(body: TrialQuestion, request: Request, response: Response, service=Depends(trial_service)):
    check_origin(request, service.identity, write=True)
    try:
        cookie = request.cookies.get(COOKIE_NAME)
        actor = service.identity.actor_hash(cookie)
        csrf = request.headers.get('x-csrf-token', '')
        if not hmac.compare_digest(csrf.encode(), service.identity.csrf(cookie).encode()):
            raise InvalidTrialIdentity('Invalid request')
        network = service.identity.network_hash(request.client.host if request.client else None,
                                                request.headers.get('x-explorer-client-ip'))
    except InvalidTrialIdentity:
        raise HTTPException(403, 'Request rejected', headers=NO_STORE) from None
    from security.public_completion import CompletionUnavailable
    try:
        result = await service.chat.answer(actor_hash=actor, network_hash=network,
            question=body.question, history=[m.model_dump() for m in body.history],
            query=body.search_query if body.search_query is not None else body.question[:120],
            document_ids=body.document_ids)
    except QuotaExceeded:
        raise HTTPException(429, 'Trial limit reached', headers=NO_STORE) from None
    except EvidenceUnavailable:
        raise HTTPException(404, 'Public evidence unavailable', headers=NO_STORE) from None
    except EvidenceChanged:
        raise HTTPException(409, 'Public evidence changed', headers=NO_STORE) from None
    except (CompletionUnavailable, IncompleteExecution, InvalidAnswer, sqlite3.Error, OSError, ValueError):
        raise HTTPException(503, 'Chat unavailable', headers=NO_STORE) from None
    response.headers.update(NO_STORE)
    return result
