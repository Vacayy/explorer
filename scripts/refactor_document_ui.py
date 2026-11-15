"""Local-only experimental document API over a disposable PostgreSQL fixture."""
import os
import re
from datetime import datetime
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException, Query, Response
import uvicorn

from models.spine import FeedDocument
from models.timeline import TimelineResponse, TimelineChannelsResponse
from models.industry import IndustryMapResponse, SectorDetailResponse, SectorPeerListResponse
from models.peers import PeerRuntime
from models.sector_peers import SectorPeersResponse
from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader
from pipeline.postgres_timeline_sources import PostgreSQLTimelineSources, GenerationTimelineResponse, GenerationExpired
from pipeline.postgres_sector_market import PostgreSQLSectorSource
from pipeline.sector_view import industry_map_from_source, sector_detail_from_source, sector_peer_list_from_source


dsn = os.environ['REFACTOR_POSTGRES_DSN']
schema = os.environ['REFACTOR_FIXTURE_SCHEMA']
params = psycopg.conninfo.conninfo_to_dict(dsn)
if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or
        (params.get('host'), params.get('dbname'), params.get('user')) != ('pg', 'fixture', 'fixture') or
        not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema)):
    raise RuntimeError('Only a disposable isolated PostgreSQL fixture is accepted')

factory = lambda: psycopg.connect(dsn, options=f'-c search_path={schema}')
reader = PostgreSQLRawDocumentReader(factory)
timeline_reader = PostgreSQLTimelineSources(factory)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get('/api/peers/runtime', response_model=PeerRuntime)
def peer_runtime():
    # Fixture only: lastAttempt can contain operational information.
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        source = PostgreSQLSectorSource(connection)
        source.generation()
        runtime = source.peer_runtime()
    if runtime is None:
        raise HTTPException(503, 'Peer 저장 자료를 읽거나 검증하지 못했습니다.')
    return runtime


@app.get('/api/spine/sector-map/peers', response_model=SectorPeersResponse)
def sector_peer_mapping():
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        source = PostgreSQLSectorSource(connection)
        source.generation()
        runtime = source.peer_runtime()
        if runtime is None:
            raise HTTPException(503, 'Peer 저장 자료를 읽거나 검증하지 못했습니다.')
        return source.sector_peers(runtime)


@app.get('/api/spine/industry/map', response_model=IndustryMapResponse)
def industry_map():
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        source = PostgreSQLSectorSource(connection)
        source.generation()
        return industry_map_from_source(source, source.peer_runtime())


@app.get('/api/spine/industry/{sector}/peers', response_model=SectorPeerListResponse)
def sector_peers(sector: str):
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        source = PostgreSQLSectorSource(connection)
        source.generation()
        runtime = source.peer_runtime()
        if runtime is None:
            raise HTTPException(503, 'Peer 저장 자료를 읽거나 검증하지 못했습니다.')
        result = sector_peer_list_from_source(source, sector, runtime)
    if result is None:
        raise HTTPException(404, '없는 섹터입니다.')
    return result


@app.get('/api/spine/industry/{sector}', response_model=SectorDetailResponse)
def sector_detail(sector: str, response: Response):
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        source = PostgreSQLSectorSource(connection)
        generation, linked = source.generation()
        result = sector_detail_from_source(source, sector, source.peer_runtime())
    if result is None:
        raise HTTPException(404, '없는 섹터입니다.')
    if linked:
        response.headers['X-Explorer-Generation'] = str(generation)
    return result


@app.get('/api/spine/feed/timeline', response_model=GenerationTimelineResponse)
def timeline(scope: Literal['all', 'sources', 'system'] = 'all',
             kind: Literal['all', 'company', 'person', 'transcript', 'trade', 'narrative', 'report', 'scenario'] = 'all',
             source: Literal['all', 'telegram', 'blog', 'youtube', 'memo'] = 'all',
             page: int = Query(1, ge=1, le=100), size: int = Query(20, ge=1, le=50),
             until: datetime | None = None, channel: str | None = Query(None, max_length=2048),
             topic: str | None = Query(None, max_length=200), generation: UUID | None = None):
    try:
        return timeline_reader.timeline(scope=scope, kind=kind, source=source, page=page, size=size,
                                        until=until.isoformat() if until else None, channel=channel, topic=topic, generation=generation)
    except GenerationExpired as exc:
        raise HTTPException(410, '조회하던 데이터가 만료됐습니다. 새로고침해 주세요.') from exc


@app.get('/api/spine/feed/channels', response_model=TimelineChannelsResponse)
def channels(response: Response, until: datetime | None = None, generation: UUID | None = None):
    try:
        result = timeline_reader.channels(until=until.isoformat() if until else None, include_owner_read_state=True, generation=generation)
        if generation is not None:
            response.headers['X-Explorer-Generation'] = str(generation)
        return result
    except GenerationExpired as exc:
        raise HTTPException(410, '조회하던 데이터가 만료됐습니다. 새로고침해 주세요.') from exc


@app.get('/api/spine/doc/{doc_id}', response_model=FeedDocument)
def document(doc_id: int, response: Response, generation: UUID | None = None):
    try:
        result, archived = reader.get_with_generation_state(doc_id, generation=generation)
    except GenerationExpired as exc:
        raise HTTPException(410, '조회하던 데이터가 만료됐습니다. 새로고침해 주세요.') from exc
    if result is None:
        raise HTTPException(404, '문서를 찾을 수 없습니다')
    if generation is not None:
        response.headers['X-Explorer-Generation'] = str(generation)
        response.headers['X-Explorer-Archived'] = '1' if archived else '0'
    return result


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)
