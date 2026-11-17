"""The single-path candidate's public access boundary (development's PublicAccessBoundary, adapted).

Differences from development's class, which stays as it was:
- 'public' reads and the new 'compute' policy resolve a session when one is present (no error without one),
  so a signed-in member reads their own personal parts and is charged for model calls; development left
  public readers without a principal.
- 'compute' (any method): every computation stays open; cost is limited where a model is actually called
  (pipeline.postgres_usage_gate). With a session cookie, a non-GET request needs the same origin and CSRF
  token as a member write; anonymous requests carry no credential to forge.
- The policy map is built from the candidate's registered routes (route_policies), with no approval filter:
  every collected-data read is public.
"""
import hmac
import re

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Match, Mount
from starlette.staticfiles import StaticFiles

from security.access_boundary import NO_STORE, effective_routes, is_api_route
from security.login_flow import SESSION_COOKIE, session_csrf

POLICIES = {'auth', 'public', 'compute', 'member', 'operator'}

_MEMBER = re.compile(r'^/api/portfolio(/|$)|^/api/spine/(saved|follows)(/|$)|^/api/spine/feed/channels/read'
                     r'|^/api/spine/home/predictions/[^/]+/pin$|^/api/spine/tracker/(conditions/|[^/]+/conditions$)')
# A member's own groups (pipeline.postgres_owner_legacy_fixture.member_rows); evaluation and reasons stay the operator's.
_MEMBER_GROUPS = re.compile(r'^/api/spine/groups(/default-watch|/[^/]+(/members(/[^/]+(/tracked)?)?|/rules)?)?$')  # each member's own ledger
# Personal ledgers not yet per principal (members get 403 until converted; tracked as open items).
_PERSONAL = re.compile(r'^/api/spine/(tracker/[^/]+/prepare$|studies|study-projects|groups/[^/]+/(evaluate|reasons)$|'
                       r'transcript/(follow|core/pin)|trade/follow)')
_ADMIN = re.compile(r'^/api/spine/(admin|approvals|agent-proposals|keywords|research/candidates|regimes/checks|client-errors|'
                    r'knowledge/items/[^/]+/(approve|reject)|narrative-candidates/)|^/api/spine/sources/(telegram|blog|youtube/[^/]+|collect)'
                    r'|^/api/(industries|business|ir-notes|blog|telegram)/|^/api/spine/knowledge$|^/api/spine/sources/youtube$')
_OPERATOR_COMPUTE = re.compile(r'^/api/analysis/(runs|discovery)|^/api/spine/tw/chain-report$|^/api/spine/proxy-boards')


def route_policy(method, path):
    if path.startswith('/api/auth/'):
        return 'auth'
    if path == '/api/spine/ask' or path.startswith('/api/spine/conversations'):
        return 'member'  # each member's own conversations (pipeline.postgres_conversations)
    if path == '/api/spine/questions/propose':
        return 'operator'  # proposes from the shared narratives into the operator's tracker
    if path.startswith('/api/spine/questions'):
        return 'member'  # each member's own tracked questions (question_principals)
    if _MEMBER.match(path):
        return 'member'
    if path == '/api/spine/groups/default-watch' or (_MEMBER_GROUPS.match(path) and method not in {'GET', 'HEAD'}):
        return 'member'  # default-watch creates the requester's default group on first read
    if _PERSONAL.match(path):  # questions too: the user's own tracked questions, read by the PG-native router
        return 'operator'
    if _ADMIN.match(path) or (_OPERATOR_COMPUTE.match(path) and method not in {'GET', 'HEAD'}):
        return 'operator'
    return 'public' if method in {'GET', 'HEAD'} else 'compute'


def route_policies(routes):
    policies = {}
    for route in effective_routes(routes):
        if is_api_route(route):
            for method in route.methods:
                policies[(method, route.path)] = route_policy(method, route.path)
    return policies


class CandidateAccessBoundary:
    def __init__(self, app, routes, service_factory, policies=None, allow_media=True):
        self.app, self.routes, self.service_factory, self.allow_media = app, routes, service_factory, allow_media
        self.policies = dict(route_policies(routes) if policies is None else policies)
        registered, self.endpoints = {}, {}
        for route in effective_routes(routes):
            if is_api_route(route):
                for method in route.methods:
                    registered[(method, route.path)] = registered.get((method, route.path), 0) + 1
                    self.endpoints[(method, route.path)] = route.endpoint
        for key, policy in self.policies.items():
            if registered.get(key) != 1 or policy not in POLICIES or (policy == 'public' and key[0] not in {'GET', 'HEAD'}):
                raise ValueError(f'Invalid or ambiguous route policy: {key}')

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
                elif (self.allow_media and isinstance(route, Mount) and route.path == '/media'
                      and isinstance(route.app, StaticFiles) and scope['method'] in {'GET', 'HEAD'}):
                    policy = 'public'
                break
        if policy is None:
            await reject(404, 'Route unavailable')
            return

        scope.setdefault('state', {})['principal'] = None
        scope['state']['public_access'] = True
        if policy != 'auth':
            request = Request(scope)
            token = request.cookies.get(SESSION_COOKIE, '')
            user = None
            if token or policy in {'member', 'operator'}:
                try:
                    service = await run_in_threadpool(self.service_factory)
                    user = await run_in_threadpool(service.identities.resolve_session, token) if token else None
                except Exception:
                    await reject(503, 'Authentication unavailable')
                    return
            if policy in {'member', 'operator'}:
                if user is None or not user.enabled or user.role not in {'member', 'operator'}:
                    await reject(401, 'Authentication required')
                    return
                if policy == 'operator' and user.role != 'operator':
                    await reject(403, 'Access denied')
                    return
            if user is not None and scope['method'] not in {'GET', 'HEAD', 'OPTIONS'}:
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
                MutableHeaders(scope=message).update(NO_STORE)
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, private_send)
        except Exception:
            if response_started:
                raise
            await reject(500, 'Request failed')
