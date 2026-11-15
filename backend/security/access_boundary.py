"""Explicit public entry boundary; endpoint ownership checks remain mandatory.

Private mode preserves the existing loopback-only application. Public mode does
not infer safety from GET, a URL prefix, a login, or a client identity header.
"""
import hmac
import os

from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Match

from security.login_flow import LoginFlow, SESSION_COOKIE, session_csrf

NO_STORE = {'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'Referrer-Policy': 'no-referrer',
            'X-Explorer-Access-Mode': 'public'}
# Only these existing endpoints have been reviewed at this stage. Each business
# route needs public projection or ownership validation before joining this map.
PUBLIC_ROUTE_POLICIES = {
    ('GET', '/api/spine/world/changes'): 'public',
    ('GET', '/api/spine/narrative'): 'public',
    ('GET', '/api/spine/narrative/list'): 'public',
    ('GET', '/api/spine/narrative/versions'): 'public',
    ('GET', '/api/spine/narrative/version'): 'public',
    ('GET', '/api/spine/narrative/{narrative_id}/diff'): 'public',
    ('GET', '/api/spine/narrative/{narrative_id}/causal'): 'public',

    ('GET', '/api/spine/home/predictions'): 'public',
    ('GET', '/api/spine/home/predictions/{event_ticker}'): 'public',
    ('GET', '/api/spine/risk'): 'public',
    ('GET', '/api/spine/credit'): 'public',
    ('GET', '/api/spine/credit/history'): 'public',
    ('GET', '/api/spine/market-regime'): 'public',
    ('GET', '/api/spine/kr/movers'): 'public',
    ('GET', '/api/spine/us/briefing'): 'public',
    ('GET', '/api/spine/us/briefing/list'): 'public',
    ('GET', '/api/spine/indices'): 'public',
    ('GET', '/api/spine/indices/breadth'): 'public',
    ('GET', '/api/spine/macro'): 'public',
    ('GET', '/api/spine/market-today'): 'public',
    ('GET', '/api/public/trade'): 'public',
    ('GET', '/api/member/saved'): 'member',
    ('POST', '/api/member/saved'): 'member',
    ('PATCH', '/api/member/saved/{item_id}'): 'member',
    ('DELETE', '/api/member/saved/{item_id}'): 'member',
    ('GET', '/api/member/portfolio/principles/rules'): 'member',
    ('GET', '/api/member/portfolio/principles/state'): 'member',
    ('GET', '/api/member/portfolio/principles'): 'member',
    ('POST', '/api/member/portfolio/principles'): 'member',
    ('PUT', '/api/member/portfolio/principles/{principle_id}'): 'member',
    ('PATCH', '/api/member/portfolio/principles/{principle_id}'): 'member',
    ('DELETE', '/api/member/portfolio/principles/{principle_id}'): 'member',
    ('GET', '/api/companies/search'): 'public',
    ('GET', '/api/companies/{stock_code}'): 'public',
    ('GET', '/api/companies/{stock_code}/prices'): 'public',
    ('GET', '/api/financials/{stock_code}'): 'public',
    ('GET', '/api/public/chat/session'): 'trial',
    ('POST', '/api/public/chat'): 'trial',
    ('GET', '/api/health'): 'public',
    ('GET', '/api/public/documents'): 'public',
    ('GET', '/api/public/feed'): 'public',
    ('GET', '/api/member/portfolio'): 'member',
    ('GET', '/api/member/portfolio/history'): 'member',
    ('GET', '/api/member/portfolio/transactions'): 'member',
    ('GET', '/api/member/portfolio/companies'): 'member',
    ('POST', '/api/member/portfolio/transactions'): 'member',
    ('DELETE', '/api/member/portfolio/transactions/{tx_id}'): 'member',
    ('GET', '/api/public/documents/{doc_id}'): 'public',
    ('GET', '/api/public/documents/{doc_id}/attachments/{attachment_id}'): 'public',
    ('GET', '/api/operator/publications/{doc_id}/preview'): 'operator',
    ('GET', '/api/operator/publications/{doc_id}/preview/{fingerprint}/attachments/{attachment_id}'): 'operator',
    ('POST', '/api/operator/publications/{doc_id}/approve'): 'operator',
    ('POST', '/api/operator/publications/{doc_id}/revoke'): 'operator',
    ('GET', '/api/spine/industry/us/map'): 'public',
    ('GET', '/api/spine/industry/map'): 'public',
    ('GET', '/api/spine/macro/public'): 'public',
    ('GET', '/api/spine/industry/{sector}/market'): 'public',
    ('GET', '/api/spine/industry/us/{ticker}/market'): 'public',
    ('GET', '/api/spine/market/{market}/overview'): 'public',
    ('GET', '/api/auth/session'): 'auth',
    ('GET', '/api/auth/google/start'): 'auth',
    ('GET', '/api/auth/google/callback'): 'auth',
    ('POST', '/api/auth/logout'): 'auth',
}


def effective_routes(routes):
    """Use included routers' effective paths (including include-time prefixes).

    The pinned FastAPI runtime keeps included routers lazy. Their effective
    contexts expose the same matches/path/methods/endpoint contract as APIRoute.
    Static mounts remain opaque and cannot be approved by this boundary.
    """
    for route in routes:
        contexts = getattr(route, 'effective_route_contexts', None)
        if callable(contexts):
            yield from contexts()
        else:
            yield route


def is_api_route(route):
    return isinstance(getattr(route, 'original_route', route), APIRoute)


class PublicAccessBoundary:
    def __init__(self, app, routes, policies=None, service_factory=LoginFlow.from_environment):
        self.app, self.routes, self.service_factory = app, routes, service_factory
        self.policies = dict(PUBLIC_ROUTE_POLICIES if policies is None else policies)
        registered = {}
        self.endpoints = {}
        for route in effective_routes(routes):
            if is_api_route(route):
                for method in route.methods:
                    key = (method, route.path)
                    registered[key] = registered.get(key, 0) + 1
                    self.endpoints[key] = route.endpoint
        for key, policy in self.policies.items():
            if (registered.get(key) != 1 or policy not in {'auth', 'public', 'member', 'operator', 'trial'}
                    or (policy == 'trial' and key not in {('GET', '/api/public/chat/session'), ('POST', '/api/public/chat')})
                    or (policy == 'public' and key[0] not in {'GET', 'HEAD'})):
                raise ValueError('Invalid or ambiguous public route policy')

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            await send({'type': 'websocket.close', 'code': 1008})
            return
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        async def reject(status, detail):
            await JSONResponse({'detail': detail}, status_code=status, headers=NO_STORE)(scope, receive, send)

        policy = None
        for route in effective_routes(self.routes):
            match, _ = route.matches(scope)
            if match == Match.FULL:
                if is_api_route(route):
                    key = (scope['method'], route.path)
                    if route.endpoint is self.endpoints.get(key):
                        policy = self.policies.get(key)
                break
        if policy is None:
            await reject(404, 'Route unavailable')
            return

        # Authentication routes implement their own state/nonce/session/CSRF
        # rules. Public readers get no member context even if a cookie exists.
        scope.setdefault('state', {})['principal'] = None
        scope['state']['public_access'] = True
        if policy in {'member', 'operator'}:
            request = Request(scope)
            token = request.cookies.get(SESSION_COOKIE, '')
            try:
                service = await run_in_threadpool(self.service_factory)
                user = await run_in_threadpool(service.identities.resolve_session, token)
            except Exception:
                await reject(503, 'Authentication unavailable')
                return
            if user is None or not user.enabled or user.role not in {'member', 'operator'}:
                await reject(401, 'Authentication required')
                return
            if policy == 'operator' and user.role != 'operator':
                await reject(403, 'Access denied')
                return
            if scope['method'] not in {'GET', 'HEAD', 'OPTIONS'}:
                csrf = request.headers.get('x-csrf-token', '')
                if (request.headers.get('origin') != service.config.public_origin
                        or not hmac.compare_digest(csrf.encode(), session_csrf(token).encode())):
                    await reject(403, 'Request rejected')
                    return
            scope['state']['principal'] = user

        response_started = False

        async def private_send(message):
            nonlocal response_started
            if message['type'] == 'http.response.start':
                # No shared response cache until reviewed public projections
                # have a separate cache contract. Applies to errors/streams too.
                headers = MutableHeaders(scope=message)
                headers.update(NO_STORE)
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, private_send)
        except Exception:
            if response_started:
                # Never append an exception message or a second response to SSE.
                raise
            await reject(500, 'Request failed')


def configured_access_mode():
    mode = os.environ.get('EXPLORER_ACCESS_MODE', 'private')
    if mode not in {'private', 'public'}:
        raise ValueError('Invalid EXPLORER_ACCESS_MODE')
    return mode


def configure_access_boundary(app, *, mode=None):
    mode = configured_access_mode() if mode is None else mode
    if mode not in {'private', 'public'}:
        raise ValueError('Invalid EXPLORER_ACCESS_MODE')
    if mode == 'public':
        app.add_middleware(PublicAccessBoundary, routes=app.router.routes)
