"""Paid model use on the single-path candidate: limited where a model is actually called, not by route.

Every computation route stays open; saved results, hash-cache hits and already-made digests answer anyone
without a model call. The first real model call of a request (pipeline.llm._execute) passes this gate:
the operator is not charged; a member's request takes one reservation from the shared chat usage quota
(development's account-hash actor) however many calls it makes; an anonymous request is refused as needing
a login. Outside a request (the loopback preview, scheduled jobs) nothing is gated. A refusal the handler
swallows still answers 401/429: the middleware reads it back from the request's usage context.
"""
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field

from fastapi.responses import JSONResponse

from security.trial_quota import QuotaExceeded

usage = ContextVar('usage_context', default=None)


class LoginRequired(PermissionError):
    pass


@dataclass
class UsageContext:
    role: str | None                  # 'operator', 'member' or None (anonymous)
    actor_hash: str | None = None
    network_hash: str | None = None
    reservation: str | None = None
    refused: str | None = None        # 'login' or a quota reason
    lock: threading.Lock = field(default_factory=threading.Lock)


def install(llm_module, quota):
    """Gate every model call of a request behind its usage context."""
    execute = llm_module._execute

    def gated(prompt, **kwargs):
        context = usage.get()
        if context is not None and context.role != 'operator':
            with context.lock:
                if context.role is None:
                    context.refused = 'login'
                    raise LoginRequired('로그인이 필요합니다')
                if context.reservation is None:
                    try:
                        context.reservation = quota.reserve(actor_hash=context.actor_hash, network_hash=context.network_hash)
                    except QuotaExceeded as exc:
                        context.refused = exc.reason
                        raise
                    quota.mark_started(context.reservation)
            try:
                return execute(prompt, **kwargs)
            finally:
                with context.lock:
                    if quota.state(context.reservation) == 'running':
                        quota.finish(context.reservation)  # one reservation per request; later calls reuse it
        return execute(prompt, **kwargs)

    llm_module._execute = gated


def add_middleware(app, *, identity):
    """After the access boundary: the request's principal (scope state) decides the usage context and whose
    personal ledgers it reads (pipeline.postgres_principals.request_principal)."""
    from pipeline.postgres_principals import request_principal

    @app.middleware('http')
    async def usage_context(request, call_next):
        user = request.scope.get('state', {}).get('principal')
        if not request.scope.get('state', {}).get('public_access'):
            return await call_next(request)  # private (loopback) mode: no boundary, no gate
        role = user.role if user is not None else None
        context = UsageContext(role=role)
        if role == 'member':
            context.actor_hash = identity.account_hash(user.id)
            context.network_hash = identity.network_hash(request.client.host if request.client else None,
                                                         request.headers.get('x-explorer-client-ip'))
        token_usage, token_principal = usage.set(context), request_principal.set(user.id if user else None)
        try:
            response = await call_next(request)
        finally:
            usage.reset(token_usage)
            request_principal.reset(token_principal)
        if context.refused == 'login':
            return JSONResponse({'detail': '로그인이 필요합니다'}, status_code=401)
        if context.refused:
            return JSONResponse({'detail': '오늘 사용할 수 있는 AI 호출을 모두 썼습니다', 'reason': context.refused}, status_code=429)
        return response
