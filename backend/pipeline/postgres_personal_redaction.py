"""Public reads that mix in the operator's personal state (single-path candidate, public mode).

Legacy screens read the owner tables the projection derives from the operator's ledgers, so their
public responses carry the operator's follows and watch lists. In the public mode, for anyone but the
operator, those parts are emptied (an anonymous visitor or another member never sees the operator's
records; a member's own appear once their ledgers are per principal). The collected-data parts are kept.
"""
import json

from starlette.responses import Response


def _home(body):
    # follows, watch-list updates and the watch flags and order of the calendar; the user's own confirmed
    # hypothesis (knowledge the user injected) leaves the briefing.
    body['follows'] = []
    body['watchlist_updates'] = []
    body['watchlist_empty'] = True
    body['calendar'] = sorted(({**event, 'in_watchlist': False} for event in body.get('calendar') or []),
                              key=lambda event: event.get('event_date') or '')
    body['briefing'] = [item for item in body.get('briefing') or [] if item.get('kind') != 'confirmed']
    return body


REDACTED = {('GET', '/api/spine/home'): _home}


def add_middleware(app):
    """Inside the access boundary (it reads the principal the boundary resolved)."""

    @app.middleware('http')
    async def personal_redaction(request, call_next):
        redact = REDACTED.get((request.method, request.url.path))
        state = request.scope.get('state', {})
        user = state.get('principal')
        if redact is None or not state.get('public_access') or (user is not None and user.role == 'operator'):
            return await call_next(request)
        response = await call_next(request)
        if response.status_code != 200:
            return response
        raw = b''.join([chunk async for chunk in response.body_iterator])
        headers = {k: v for k, v in response.headers.items() if k.lower() not in {'content-length', 'content-encoding'}}
        return Response(json.dumps(redact(json.loads(raw)), ensure_ascii=False), status_code=200, headers=headers,
                        media_type='application/json')
