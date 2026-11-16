"""Existing member router and boundary against a disposable PG ledger."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import psycopg
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import member_portfolio as routes
    from security.access_boundary import PublicAccessBoundary, PUBLIC_ROUTE_POLICIES
    from security.identity_store import IdentityStore
    from security.login_flow import SESSION_COOKIE, session_csrf
    from security.member_portfolio import TransactionUnavailable
except ImportError:
    if os.getenv('REFACTOR_TEST_DISPOSABLE')=='1' and os.getenv('REFACTOR_POSTGRES_DSN'):
        raise
    psycopg=None

from pipeline.postgres_portfolio_fixture import MemberPortfolioFixture, initialize


@unittest.skipUnless(psycopg and os.getenv('REFACTOR_POSTGRES_DSN') and os.getenv('REFACTOR_TEST_DISPOSABLE')=='1',
                     'disposable PostgreSQL and existing member boundary required')
class MemberHTTPFixtureTests(unittest.TestCase):
    def test_existing_session_boundary_and_member_ledger(self):
        dsn=os.environ['REFACTOR_POSTGRES_DSN']
        if tuple(psycopg.conninfo.conninfo_to_dict(dsn).get(k) for k in ('host','dbname','user')) != ('pg','fixture','fixture'):
            raise RuntimeError('Refusing non-fixture PostgreSQL')
        schema='refactor_fixture_'+uuid.uuid4().hex
        with psycopg.connect(dsn) as conn:
            conn.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(schema)))
        def factory():
            return psycopg.connect(dsn,options='-c search_path='+schema)
        try:
            with factory() as conn:
                initialize(conn)
            with tempfile.TemporaryDirectory() as tmp:
                identities=IdentityStore(Path(tmp)/'identities.sqlite')
                identities.initialize()
                tokens=[]
                for name in ('a','b'):
                    user=identities.get_or_create_google_user('accounts.google.com',name)
                    tokens.append(identities.issue_session(user.id,ttl_seconds=3600))
                app=FastAPI()
                app.include_router(routes.router)
                policies={k:v for k,v in PUBLIC_ROUTE_POLICIES.items() if k[1].startswith('/api/member/portfolio')}
                app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies=policies,
                    service_factory=lambda:SimpleNamespace(identities=identities,config=SimpleNamespace(public_origin='https://beta.example')))
                def service(_source,owner):
                    return MemberPortfolioFixture(factory,owner,names={'000001':'합성 회사'},
                        prices=lambda *_:({'000001':[('2026-01-01',10),('2026-01-02',12)]},{}),
                        last_close=lambda *_:10,unavailable=TransactionUnavailable)
                def headers(token):
                    return {'Cookie':SESSION_COOKIE+'='+token,'Origin':'https://beta.example','X-CSRF-Token':session_csrf(token)}
                body={'trade_date':'2026-01-01','kind':'buy','stock_code':'000001','amount':100,'price':10}
                with patch.object(routes,'MemberPortfolio',side_effect=service), TestClient(app,base_url='https://beta.example') as client:
                    path='/api/member/portfolio/transactions'
                    self.assertEqual(client.get(path).status_code,401)
                    self.assertEqual(client.post(path,headers={'Cookie':SESSION_COOKIE+'='+tokens[0]},json=body).status_code,403)
                    added=client.post(path,headers=headers(tokens[0]),json=body)
                    self.assertEqual(added.status_code,200)
                    ident=added.json()['id']
                    self.assertEqual(client.delete(path+'/'+str(ident),headers=headers(tokens[1])).status_code,404)
                    self.assertEqual(client.get(path,headers=headers(tokens[1])).json(),[])
                    result=client.get(path,headers=headers(tokens[0]))
                    self.assertEqual(result.status_code,200)
                    self.assertEqual(result.headers['cache-control'],'no-store')
                    self.assertNotIn('amount',result.json()[0])
        finally:
            with psycopg.connect(dsn) as conn:
                conn.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(schema)))
