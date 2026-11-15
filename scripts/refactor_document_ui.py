"""Local-only experimental document API over a disposable PostgreSQL fixture."""
import os
import re
from datetime import datetime
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException, Query
import uvicorn

from models.spine import FeedDocument
from models.timeline import TimelineResponse, TimelineChannelsResponse
from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader
from pipeline.postgres_timeline_sources import PostgreSQLTimelineSources, GenerationTimelineResponse, GenerationExpired


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
def channels(until: datetime | None = None, generation: UUID | None = None):
    try:
        return timeline_reader.channels(until=until.isoformat() if until else None, include_owner_read_state=True, generation=generation)
    except GenerationExpired as exc:
        raise HTTPException(410, '조회하던 데이터가 만료됐습니다. 새로고침해 주세요.') from exc


@app.get('/api/spine/doc/{doc_id}', response_model=FeedDocument)
def document(doc_id: int, generation: UUID | None = None):
    try:
        result = reader.get(doc_id, generation=generation)
    except GenerationExpired as exc:
        raise HTTPException(410, '조회하던 데이터가 만료됐습니다. 새로고침해 주세요.') from exc
    if result is None:
        raise HTTPException(404, '문서를 찾을 수 없습니다')
    return result


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)
