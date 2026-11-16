"""Local-only HTTPS browser fixture; never opens a production database."""
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
import psycopg
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse
import uvicorn

from pipeline.postgres_member_app_fixture import create_app
from pipeline.postgres_portfolio_fixture import initialize
from security.identity_store import IdentityStore

dsn=os.environ['REFACTOR_POSTGRES_DSN']
schema=os.environ['REFACTOR_FIXTURE_SCHEMA']
params=psycopg.conninfo.conninfo_to_dict(dsn)
if (os.getenv('REFACTOR_TEST_DISPOSABLE')!='1' or
        tuple(params.get(k) for k in ('host','dbname','user')) != ('pg','fixture','fixture') or
        not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',schema)):
    raise RuntimeError('Disposable PostgreSQL fixture required')
origin='https://localhost:19446'
state=Path('/preview-state')
site=StaticFiles(directory='/site',html=True)
identities=IdentityStore(state/'identity.sqlite')
identities.initialize()
user=identities.get_or_create_google_user('accounts.google.com','synthetic-preview-member')
token=identities.issue_session(user.id,ttl_seconds=3600)
session=state/'session.json'
descriptor=os.open(session,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(descriptor,'w') as out:
    json.dump({'token':token},out)

def factory():
    return psycopg.connect(dsn,options='-c search_path='+schema)

with factory() as conn:
    initialize(conn)
    conn.execute('CREATE TABLE sector_market_metadata(singleton BOOLEAN)')
    conn.execute('CREATE TABLE sector_market_companies(stock_code TEXT,corp_name TEXT)')
    conn.execute('CREATE TABLE sector_market_prices(stock_code TEXT,trade_date TEXT,close BIGINT)')
    conn.execute('INSERT INTO sector_market_metadata VALUES (TRUE)')
    conn.execute("INSERT INTO sector_market_companies VALUES ('000001','합성 테스트 기업')")
    conn.execute("INSERT INTO sector_market_prices VALUES ('000001','2026-01-01',10),('000001','2026-01-02',12)")

api=create_app(factory,identity_service=SimpleNamespace(identities=identities,config=SimpleNamespace(public_origin=origin)))


async def app(scope,receive,send):
    if scope['type']!='http' or scope['path'].startswith('/api'):
        await api(scope,receive,send)
        return
    try:
        await site(scope,receive,send)
    except HTTPException as error:
        if error.status_code!=404 or scope['method']!='GET' or '.' in scope['path'].rsplit('/',1)[-1]:
            raise
        await FileResponse('/site/index.html',headers={'Cache-Control':'no-store'})(scope,receive,send)


if __name__=='__main__':
    uvicorn.run(app,host='0.0.0.0',port=19446,ssl_certfile='/preview-state/cert.pem',ssl_keyfile='/preview-state/key.pem',access_log=False)
