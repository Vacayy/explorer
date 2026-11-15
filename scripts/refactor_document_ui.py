"""Local-only experimental document API over a disposable PostgreSQL fixture."""
import os
import re
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException, Query, Response
import uvicorn

from models.spine import FeedDocument, FeedResponse, SignalsResponse
from models.timeline import TimelineResponse, TimelineChannelsResponse
from models.industry import IndustryMapResponse, SectorDetailResponse, SectorPeerListResponse
from models.peers import PeerRuntime
from models.sector_peers import SectorPeersResponse
from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader
from pipeline.postgres_document_read import PostgreSQLDocumentReader
from pipeline.postgres_timeline_sources import PostgreSQLTimelineSources, GenerationTimelineResponse, GenerationExpired, resolve_generation
from pipeline.postgres_sector_market import PostgreSQLSectorSource
from pipeline.postgres_search_snapshot import SearchSnapshot
from pipeline.postgres_search_feed import search_feed
from pipeline.postgres_document_claims import claims_state
from pipeline.postgres_signals_fixture import signals_items, signals_summary, mention_momentum
from routers.spine_signals import SignalsSummary, MomentumResponse
from pipeline.postgres_narrative_fixture import list_narratives, cached_narrative
from routers.spine_narrative import NarrativeList, Narrative
from routers.spine_doc import DocClaims, RelatedDoc
from pipeline.postgres_related_documents import CentroidIndex, related_documents
from pipeline.postgres_us_sectors import us_map as postgres_us_map, us_sector_detail as postgres_us_sector_detail
from pipeline.sector_view import industry_map_from_source, sector_detail_from_source, sector_peer_list_from_source
from models.industry import UsIndustryMapResponse, UsSectorDetailResponse


dsn = os.environ['REFACTOR_POSTGRES_DSN']
schema = os.environ['REFACTOR_FIXTURE_SCHEMA']
params = psycopg.conninfo.conninfo_to_dict(dsn)
if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or
        (params.get('host'), params.get('dbname'), params.get('user')) != ('pg', 'fixture', 'fixture') or
        not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema)):
    raise RuntimeError('Only a disposable isolated PostgreSQL fixture is accepted')

factory = lambda: psycopg.connect(dsn, options=f'-c search_path={schema}')
reader = PostgreSQLRawDocumentReader(factory)
list_reader = PostgreSQLDocumentReader(factory)
timeline_reader = PostgreSQLTimelineSources(factory)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
search_lock = threading.RLock()
search_index = None
related_index = None


@app.get('/api/spine/signals', response_model=SignalsResponse)
def experimental_signals(type: str | None = None, days: int = Query(7,ge=1,le=90)):
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if not connection.execute("SELECT 1 FROM legacy_snapshot_tables WHERE table_name='signals'").fetchone():
            raise HTTPException(503,'신호 자료가 준비되지 않았습니다.')
        items=signals_items(connection,since=(date.today()-timedelta(days=days)).isoformat(),signal_type=type)
        return SignalsResponse(items=items,as_of=datetime.now(timezone.utc).isoformat())


@app.get('/api/spine/signals/summary', response_model=SignalsSummary)
def experimental_signals_summary(days: int = Query(7,ge=1,le=90)):
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if not connection.execute("SELECT 1 FROM legacy_snapshot_tables WHERE table_name='signals'").fetchone():
            raise HTTPException(503,'신호 자료가 준비되지 않았습니다.')
        return signals_summary(connection,days=days)


@app.get('/api/spine/signals/momentum', response_model=MomentumResponse)
def experimental_momentum(limit: int = Query(12,ge=3,le=30)):
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return mention_momentum(connection,limit=limit)


@app.get('/api/spine/narrative/list', response_model=NarrativeList)
def experimental_narrative_list():
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        try:
            return list_narratives(connection)
        except ValueError as exc:
            raise HTTPException(503,'내러티브 자료가 준비되지 않았습니다.') from exc


@app.get('/api/spine/narrative', response_model=Narrative)
def experimental_narrative_detail(topic: str):
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return cached_narrative(connection,topic)


@app.get('/api/spine/feed', response_model=FeedResponse)
def experimental_search_feed(response: Response, q: str | None = Query(None, max_length=200),
                             source: str | None = None, page: int = Query(1, ge=1),
                             size: int = Query(20, ge=1, le=100), stock: str | None = None,
                             industry: str | None = None, topic: str | None = None,
                             days: int | None = Query(None, ge=1, le=3650),
                             sort: Literal['relevance', 'latest'] = 'relevance'):
    # Serializing rebuilds and queries prevents a replaced generation from
    # closing an index while another request is using it. Fixture only.
    global search_index
    if not q or not q.strip():
        return list_reader.list(page=page, size=size, source=source, stock=stock,
                                industry=industry, topic=topic, days=days)
    with search_lock, factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        generation = connection.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
        if generation is None:
            raise HTTPException(503, '검색 자료가 준비되지 않았습니다.')
        if search_index is None or search_index.generation != str(generation[0]):
            replacement = SearchSnapshot.from_postgres(connection)
            previous, search_index = search_index, replacement
            if previous is not None:
                previous.close()
        vector = None
        try:
            from pipeline.search import _get_model, _serialize
            vector = _serialize(next(iter(_get_model(local_files_only=True).embed([q]))))
        except Exception:
            # The original search retains lexical results when the model is unavailable.
            pass
        result = search_feed(connection, search_index, q, vector=vector, source=source, stock=stock,
                             industry=industry, topic=topic, days=days, sort=sort, page=page, size=size)
        response.headers['X-Explorer-Generation'] = search_index.generation
        return result


def check_sector_generation(source, requested, response):
    current, linked = source.generation()
    if requested is not None and (not linked or requested != current):
        raise HTTPException(410, '조회하던 산업 자료가 갱신됐습니다. 다시 열어 주세요.')
    if linked:
        response.headers['X-Explorer-Generation'] = str(current)


@app.get('/api/peers/runtime', response_model=PeerRuntime)
def peer_runtime(response: Response, generation: UUID | None = None):
    # Fixture only: lastAttempt can contain operational information.
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        source = PostgreSQLSectorSource(connection)
        check_sector_generation(source, generation, response)
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


@app.get('/api/spine/industry/us/map', response_model=UsIndustryMapResponse)
def us_industry_map():
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        try:
            return postgres_us_map(connection)
        except ValueError as exc:
            raise HTTPException(503, '미국 산업 자료가 준비되지 않았습니다.') from exc


@app.get('/api/spine/industry/us/{ticker}', response_model=UsSectorDetailResponse)
def us_sector_detail(ticker: str):
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        try:
            result = postgres_us_sector_detail(connection, ticker)
        except ValueError as exc:
            raise HTTPException(503, '미국 산업 자료가 준비되지 않았습니다.') from exc
    if result is None:
        raise HTTPException(404, '없는 미국 섹터입니다.')
    return result


@app.get('/api/spine/industry/{sector}/peers', response_model=SectorPeerListResponse)
def sector_peers(sector: str, response: Response, generation: UUID | None = None):
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        source = PostgreSQLSectorSource(connection)
        check_sector_generation(source, generation, response)
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
def timeline(response: Response, scope: Literal['all', 'sources', 'system'] = 'all',
             kind: Literal['all', 'company', 'person', 'transcript', 'trade', 'narrative', 'report', 'scenario'] = 'all',
             source: Literal['all', 'telegram', 'blog', 'youtube', 'memo'] = 'all',
             page: int = Query(1, ge=1, le=100), size: int = Query(20, ge=1, le=50),
             until: datetime | None = None, channel: str | None = Query(None, max_length=2048),
             topic: str | None = Query(None, max_length=200), generation: UUID | None = None):
    try:
        result = timeline_reader.timeline(scope=scope, kind=kind, source=source, page=page, size=size,
                                          until=until.isoformat() if until else None, channel=channel, topic=topic, generation=generation)
        with factory() as connection:
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            resolve_generation(connection, result.generation)
            if connection.execute('SELECT EXISTS(SELECT 1 FROM media_generations WHERE generation_id=%s)',
                                  (result.generation,)).fetchone()[0]:
                response.headers['X-Explorer-Media-Generation'] = result.generation
        return result
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
        with factory() as connection:
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            if connection.execute('SELECT EXISTS(SELECT 1 FROM media_generations WHERE generation_id=%s)',
                                  (generation,)).fetchone()[0]:
                response.headers['X-Explorer-Media-Generation'] = str(generation)
    return result


@app.get('/api/spine/doc/{doc_id}/claims', response_model=DocClaims)
def document_claims(doc_id: int, generation: UUID | None = None):
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if generation is not None:
            try:
                _, archived = resolve_generation(connection, generation)
            except GenerationExpired as exc:
                raise HTTPException(410, '조회하던 데이터가 만료됐습니다.') from exc
            if archived:
                raise HTTPException(410, '이전 자료의 논점은 사용할 수 없습니다.')
        try:
            result = claims_state(connection, doc_id)
        except ValueError as exc:
            raise HTTPException(503, '논점 자료가 준비되지 않았습니다.') from exc
    if result is None:
        raise HTTPException(404, '문서를 찾을 수 없습니다')
    return result


@app.get('/api/spine/doc/{doc_id}/related', response_model=list[RelatedDoc])
def document_related(doc_id: int, generation: UUID | None = None):
    global related_index
    with search_lock, factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if generation is not None:
            try:
                _, archived = resolve_generation(connection, generation)
            except GenerationExpired as exc:
                raise HTTPException(410, '조회하던 데이터가 만료됐습니다.') from exc
            if archived:
                raise HTTPException(410, '이전 자료의 관련 문서는 사용할 수 없습니다.')
        current = connection.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
        if current is None:
            raise HTTPException(503, '관련 문서 자료가 준비되지 않았습니다.')
        if related_index is None or related_index.generation != str(current[0]):
            try:
                replacement = CentroidIndex.from_postgres(connection)
            except ValueError as exc:
                raise HTTPException(503, '관련 문서 자료가 준비되지 않았습니다.') from exc
            previous, related_index = related_index, replacement
            if previous is not None:
                previous.close()
        return related_documents(connection, related_index, doc_id)


@app.get('/api/refactor/media/{generation}/{media_path:path}')
def generation_media(generation: UUID, media_path: str):
    with factory() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        try:
            resolve_generation(connection, generation)
        except GenerationExpired as exc:
            raise HTTPException(410, '조회하던 자료가 만료됐습니다.') from exc
        row = connection.execute('''SELECT b.content FROM media_generation_refs r
            JOIN media_blobs b ON b.digest=r.digest WHERE r.generation_id=%s AND r.path=%s''',
                                 (generation, media_path)).fetchone()
    if not row:
        raise HTTPException(404, '첨부를 찾을 수 없습니다.')
    suffix = media_path.rsplit('.', 1)[-1].lower()
    types = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
             'gif': 'image/gif', 'webp': 'image/webp'}
    if suffix not in types:
        raise HTTPException(404, '첨부를 찾을 수 없습니다.')
    return Response(content=bytes(row[0]), media_type=types[suffix],
                    headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store'})


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)
