"""Proxy boards (D-240) on the single-path candidate: reads only, for now.

The source had no boards as of the base snapshot (11-14); the question import created the two tables, empty,
as PG-native ledgers, and the projection shows them (`NATIVE`), so the legacy list and detail reads answer
their normal empty state. Board and item writes and the suggestion stay unavailable
(answered as such) until the final sync finds boards on the MacBook or the owner asks for them.
"""
from fastapi import APIRouter, HTTPException

WRITES = (('POST', ''), ('POST', '/'), ('POST', '/suggest'), ('PATCH', '/{board_id}'), ('DELETE', '/{board_id}'),
          ('POST', '/{board_id}/items'), ('DELETE', '/{board_id}/items/{proxy_id}'), ('PUT', '/{board_id}/items/order'))


def create_router():
    router = APIRouter(prefix='/api/spine/proxy-boards')

    def unavailable():
        raise HTTPException(501, '프록시 보드 만들기·편집은 후보에서 아직 지원하지 않습니다')

    for method, path in WRITES:
        router.add_api_route(path, unavailable, methods=[method], include_in_schema=False)
    return router
