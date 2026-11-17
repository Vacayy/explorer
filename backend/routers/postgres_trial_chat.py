"""Anonymous trial chat routes on the candidate (public mode only), development's contract unchanged.

GET /api/public/chat/session issues the signed trial cookie and returns the remaining count and CSRF token;
POST /api/public/chat answers one question from the collected documents (pipeline.postgres_trial_chat). A
signed-in member is counted by account, everyone else by the trial cookie. Transcript data stays in memory.
"""
import hmac

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from models.trial_chat import TrialAnswer, TrialQuestion, TrialSession
from pipeline.postgres_trial_chat import EvidenceChanged, EvidenceUnavailable
from security.access_boundary import NO_STORE
from security.login_flow import SESSION_COOKIE
from security.trial_identity import COOKIE_NAME, COOKIE_TTL, InvalidTrialIdentity
from security.trial_quota import QuotaExceeded

BODY_LIMIT = 96 * 1024
ROUTES = ('/api/public/chat/session', '/api/public/chat')


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


def create_router(identity, quota, identities, chat):
    router = APIRouter(tags=['trial-chat'], route_class=TrialRoute)

    def check_origin(request, write=False):
        if not identity.valid_origin(request.headers.get('origin'), request.headers.get('sec-fetch-site'), write):
            raise HTTPException(403, 'Request rejected', headers=NO_STORE)

    def actor_for_request(request, cookie):
        # Verify the browser cookie even for an account: it also binds CSRF.
        anonymous_actor = identity.actor_hash(cookie)
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return anonymous_actor
        try:
            user = identities.resolve_session(token)
        except Exception:
            raise HTTPException(503, 'Authentication unavailable', headers=NO_STORE) from None
        if user is None or not user.enabled:
            raise HTTPException(401, 'Authentication required', headers=NO_STORE)
        return identity.account_hash(user.id)

    @router.get('/api/public/chat/session', response_model=TrialSession)
    def session(request: Request, response: Response):
        check_origin(request)
        cookie = request.cookies.get(COOKIE_NAME)
        try:
            identity.actor_hash(cookie)
        except InvalidTrialIdentity:
            cookie = identity.issue_cookie()
            response.set_cookie(COOKIE_NAME, cookie, max_age=COOKIE_TTL, secure=True,
                                httponly=True, samesite='lax', path='/')
        actor = actor_for_request(request, cookie)
        try:
            remaining = quota.remaining(actor)
        except Exception:
            raise HTTPException(503, 'Chat unavailable', headers=NO_STORE) from None
        response.headers.update(NO_STORE)
        return {'remaining': remaining, 'limit': quota.policy.per_actor_limit, 'csrf_token': identity.csrf(cookie)}

    @router.post('/api/public/chat', response_model=TrialAnswer)
    async def ask(body: TrialQuestion, request: Request, response: Response):
        check_origin(request, write=True)
        try:
            cookie = request.cookies.get(COOKIE_NAME)
            actor = actor_for_request(request, cookie)
            csrf = request.headers.get('x-csrf-token', '')
            if not hmac.compare_digest(csrf.encode(), identity.csrf(cookie).encode()):
                raise InvalidTrialIdentity('Invalid request')
            network = identity.network_hash(request.client.host if request.client else None,
                                            request.headers.get('x-explorer-client-ip'))
        except InvalidTrialIdentity:
            raise HTTPException(403, 'Request rejected', headers=NO_STORE) from None
        try:
            result = await run_in_threadpool(
                chat.answer, actor_hash=actor, network_hash=network, question=body.question,
                history=[m.model_dump() for m in body.history],
                query=body.search_query if body.search_query is not None else body.question[:120],
                document_ids=body.document_ids)
        except QuotaExceeded:
            raise HTTPException(429, 'Trial limit reached', headers=NO_STORE) from None
        except EvidenceUnavailable:
            raise HTTPException(404, 'Public evidence unavailable', headers=NO_STORE) from None
        except EvidenceChanged:
            raise HTTPException(409, 'Public evidence changed', headers=NO_STORE) from None
        except Exception:  # IncompleteExecution, InvalidAnswer, provider failures: a fixed answer, no detail
            raise HTTPException(503, 'Chat unavailable', headers=NO_STORE) from None
        response.headers.update(NO_STORE)
        return result

    return router
