"""Local-only experimental document API over a disposable PostgreSQL fixture."""
import os
import re

import psycopg
from fastapi import FastAPI, HTTPException
import uvicorn

from models.spine import FeedDocument
from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader


dsn = os.environ['REFACTOR_POSTGRES_DSN']
schema = os.environ['REFACTOR_FIXTURE_SCHEMA']
params = psycopg.conninfo.conninfo_to_dict(dsn)
if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or
        (params.get('host'), params.get('dbname'), params.get('user')) != ('pg', 'fixture', 'fixture') or
        not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema)):
    raise RuntimeError('Only a disposable isolated PostgreSQL fixture is accepted')

reader = PostgreSQLRawDocumentReader(lambda: psycopg.connect(dsn, options=f'-c search_path={schema}'))
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get('/api/spine/doc/{doc_id}', response_model=FeedDocument)
def document(doc_id: int):
    result = reader.get(doc_id)
    if result is None:
        raise HTTPException(404, '문서를 찾을 수 없습니다')
    return result


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)
