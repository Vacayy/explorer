"""Loopback-only owner follows, prediction pins, feed read marks and bookmarks on the PG ledger.

Same request/response shapes and errors as the legacy routes. The follow list
and feed read marks read the ledger directly; legacy reads (prediction cards)
see it through the projection's per-connection TEMP shadows, so writes show at once. Never serve beyond the
private loopback gateway; external exposure needs the owner gate first.
"""
from fastapi import APIRouter, HTTPException, Path
from fastapi.routing import APIRoute

from models.kalshi import KalshiPinBody, KalshiPinResult
from models.timeline import MarkAllReadResponse
from pipeline.timeline import utc
from pipeline import postgres_owner_records_fixture as records
from routers.spine_feed import MarkAllReadRequest, MarkReadRequest
from routers.spine_follows import FollowedEntity, FollowRequest
from routers.spine_saved import NoteRequest, SavedItem, SaveRequest


def create_router(factory, timeline):
    router = APIRouter()

    def connection():
        conn = factory()
        try:
            records.owner_account(conn)
        except LookupError:
            conn.close()
            raise HTTPException(503, 'Owner records unavailable') from None
        return conn

    @router.get('/api/spine/follows', response_model=list[FollowedEntity])
    def list_follows():
        with connection() as conn:
            return records.follows(conn)

    @router.post('/api/spine/follows', response_model=FollowedEntity, status_code=201)
    def add_follow(body: FollowRequest):
        if not body.entity_id and not (body.type and body.name):
            raise HTTPException(400, 'entity_id 또는 (type, name) 필요')
        with connection() as conn:
            row = (records.entity(conn, ident=body.entity_id) if body.entity_id
                   else records.entity(conn, kind=body.type, name=body.name))
            if not row:
                raise HTTPException(404, '엔티티를 찾을 수 없습니다')
            records.follow(conn, int(row['id']))
        return FollowedEntity(entity_id=int(row['id']), type=row['type'], name=row['name'])

    @router.delete('/api/spine/follows/{entity_id}', status_code=204)
    def remove_follow(entity_id: int):
        with connection() as conn:
            records.unfollow(conn, entity_id)

    @router.post('/api/spine/home/predictions/{event_ticker}/pin', response_model=KalshiPinResult)
    def prediction_pin(body: KalshiPinBody, event_ticker: str = Path(..., pattern=r'^[A-Za-z0-9._-]{1,80}$')):
        with connection() as conn:
            return {'event_ticker': event_ticker, 'pinned': records.set_pin(conn, event_ticker, body.series_ticker, body.pinned)}

    @router.post('/api/spine/feed/channels/read')
    def mark_channel_read(body: MarkReadRequest):
        if not body.channel or len(body.channel) > 300:
            raise HTTPException(400, 'channel required')
        try:
            stamp = utc(body.read_until)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        with connection() as conn:
            return {'channel': body.channel, 'read_until': records.mark_read(conn, body.channel, stamp)}

    @router.post('/api/spine/feed/channels/read-all', response_model=MarkAllReadResponse)
    def mark_all_channels_read(body: MarkAllReadRequest):
        try:
            stamp = utc(body.read_until)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        # Same targets as the legacy rule: human sources in scope with unread items up to read_until.
        targets = [c for c in timeline.channels(until=stamp, include_owner_read_state=True).items
                   if c.platform != 'system' and (body.platform == 'all' or c.platform == body.platform) and c.unread > 0]
        with connection() as conn:
            for c in targets:
                records.mark_read(conn, c.id, stamp)
        return {'platform': body.platform, 'read_until': stamp, 'channels': len(targets), 'marked': sum(c.unread for c in targets)}

    @router.post('/api/spine/saved', response_model=SavedItem, status_code=201)
    def add_saved(body: SaveRequest):
        if body.kind not in ('company', 'doc', 'narrative', 'report', 'chat'):
            raise HTTPException(400, '알 수 없는 kind')
        with connection() as conn:
            return records.save(conn, body)

    @router.patch('/api/spine/saved/{item_id}', response_model=SavedItem)
    def update_note(item_id: int, body: NoteRequest):
        with connection() as conn:
            row = records.update_saved_note(conn, item_id, body.note)
        if row is None:
            raise HTTPException(404, '저장 항목을 찾을 수 없습니다')
        return row

    @router.delete('/api/spine/saved/{item_id}', status_code=204)
    def remove_saved(item_id: int):
        with connection() as conn:
            records.remove_saved(conn, item_id)

    return router


def install(app, factory, timeline):
    """Put the ledger routes ahead of the read-only legacy routes with the same path."""
    router = create_router(factory, timeline)
    owned = {(route.path, method) for route in router.routes for method in route.methods}
    app.router.routes[:] = [route for route in app.router.routes
                            if not (isinstance(route, APIRoute) and any((route.path, m) in owned for m in route.methods))]
    app.router.routes[0:0] = list(router.routes)
