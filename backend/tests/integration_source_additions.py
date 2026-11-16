"""Adding telegram/blog/youtube sources with the external checks mocked (no request leaves the process).

Run only through `scripts/refactor_run_collector_once.sh backend/tests/integration_source_additions.py run|restore`.
"""
import os
import socket
import sys

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

DSN, SCHEMA = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
PG_HOST = psycopg.conninfo.conninfo_to_dict(DSN)['host']
real_getaddrinfo = socket.getaddrinfo


def only_pg(host, *args, **kwargs):  # any other lookup means a real external request
    if host != PG_HOST:
        raise RuntimeError(f'external request blocked: {host}')
    return real_getaddrinfo(host, *args, **kwargs)


socket.getaddrinfo = only_pg
factory = lambda: psycopg.connect(DSN, options=f'-c search_path={SCHEMA}')
KEYS = (('telegram', 'synthetic_rv5'), ('blog', 'https://synthetic-rv5.example'), ('youtube', 'UCsyntheticRV5'))


def run():
    import database
    import services.blog_service as blog
    import services.telegram_service as telegram
    from pipeline.connectors import youtube
    from pipeline.postgres_legacy_projection import LegacyProjection
    from routers.postgres_owner_records_fixture import create_router
    projection = LegacyProjection(factory, '/projection', external=True)
    database.get_connection = projection.connect  # dup checks read the projection with owner shadows, as in the preview
    telegram.scrape_channel = lambda channel: [{'text': 'preview'}] * 3
    telegram.get_channel_display_name = lambda channel: '합성 채널 RV5'
    blog.detect_platform_and_feed_url = lambda url: ('rss', url + '/feed')
    blog.verify_and_fetch = lambda feed: ([{'title': 'post'}] * 2, '합성 블로그 RV5')
    blog.fetch_blog_author = lambda url, posts: '합성 저자'
    youtube.resolve_channel_id = lambda s: ('UCsyntheticRV5', '합성 유튜브 RV5')
    app = FastAPI()
    app.include_router(create_router(factory, None))
    client = TestClient(app)
    for path, body in (('telegram', {'channel': 'https://t.me/synthetic_rv5'}), ('blog', {'url': 'synthetic-rv5.example/'}),
                       ('youtube', {'input': '@syntheticRV5'})):
        first = client.post(f'/api/spine/sources/{path}', json=body)
        print(path, first.status_code, first.json())
    with factory() as pg:
        print('ledger', pg.execute('SELECT kind,key,row_data->>\'id\' FROM owner_source_additions ORDER BY kind').fetchall())
    # The builder's next projection shows them; a second add of the same source is then a 409.


def restore():
    with factory() as pg:
        print('removed', sum(pg.execute('DELETE FROM owner_source_additions WHERE kind=%s AND key=%s', pair).rowcount
                             for pair in KEYS))


{'run': run, 'restore': restore}[sys.argv[1]]()
