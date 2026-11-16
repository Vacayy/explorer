"""Loopback-only owner follows and prediction pins on the PG ledger.

Same request/response shapes and errors as the legacy routes. The follow list
reads the ledger directly so a toggle shows at once; prediction cards read pins
through the projection and follow within its rebuild. Never serve beyond the
private loopback gateway; external exposure needs the owner gate first.
"""
from fastapi import APIRouter, HTTPException, Path
from fastapi.routing import APIRoute

from models.kalshi import KalshiPinBody, KalshiPinResult
from pipeline import postgres_owner_records_fixture as records
from routers.spine_follows import FollowedEntity, FollowRequest


def create_router(factory):
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

    return router


def install(app, factory):
    """Put the ledger routes ahead of the read-only legacy routes with the same path."""
    router = create_router(factory)
    owned = {(route.path, method) for route in router.routes for method in route.methods}
    app.router.routes[:] = [route for route in app.router.routes
                            if not (isinstance(route, APIRoute) and any((route.path, m) in owned for m in route.methods))]
    app.router.routes[0:0] = list(router.routes)
