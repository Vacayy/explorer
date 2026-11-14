"""Synthetic ledger ownership, ASGI access and atomic concurrent writes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from models.portfolio import TransactionCreate
from pipeline import portfolio as pf
from routers import member_portfolio as routes
from security.access_boundary import PublicAccessBoundary, PUBLIC_ROUTE_POLICIES
from security.identity_store import IdentityStore
from security.login_flow import SESSION_COOKIE, session_csrf
from security.member_portfolio import MemberPortfolio, initialize_ownership
from tests.test_portfolio import db, prices, tx


class MemberPortfolioTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/'source.sqlite'
        fixture = db()
        prices(fixture,'AAAAAA',[('2026-01-01',10),('2026-01-02',12)])
        tx(fixture,trade_date='2026-01-01',kind='buy',stock_code='AAAAAA',amount=100,price=10)
        self.legacy_summary = pf.summary(fixture)
        self.legacy_transactions = pf.transactions(fixture)
        self.legacy_gid = pf.group_id(fixture)
        fixture.execute('CREATE TABLE private_records(id INTEGER PRIMARY KEY, note TEXT)')
        fixture.execute("INSERT INTO private_records VALUES(1,'operator-private-canary')")
        fixture.commit()
        with sqlite3.connect(self.path) as target: fixture.backup(target)
        fixture.close()
        with self.connect() as conn: initialize_ownership(conn)
        self.identities = IdentityStore(Path(tmp.name)/'identity.sqlite'); self.identities.initialize()
        self.headers={};self.users={};self.tokens={}
        for name in ['a','b','operator']:
            user=self.identities.get_or_create_google_user('accounts.google.com',name)
            if name=='operator': self.identities.set_role(user.id,'operator')
            token=self.identities.issue_session(user.id,ttl_seconds=3600)
            self.users[name]=user.id; self.tokens[name]=token
            self.headers[name]={'Cookie':SESSION_COOKIE+'='+token,'Origin':'https://beta.example','X-CSRF-Token':session_csrf(token)}
        app=FastAPI();app.include_router(routes.router)
        policies={k:v for k,v in PUBLIC_ROUTE_POLICIES.items() if k[1].startswith('/api/member/portfolio')}
        app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies=policies,
            service_factory=lambda:SimpleNamespace(identities=self.identities,config=SimpleNamespace(public_origin='https://beta.example')))
        self.client=TestClient(app,base_url='https://beta.example');self.addCleanup(self.client.close)
        p=patch('config.DB_PATH',self.path);p.start();self.addCleanup(p.stop)
        self.base='/api/member/portfolio'

    @contextmanager
    def connect(self):
        conn=sqlite3.connect(self.path);conn.row_factory=sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def add(self, name='a', **overrides):
        body={'trade_date':'2026-01-01','kind':'buy','stock_code':'AAAAAA','amount':50,'price':10,**overrides}
        return self.client.post(self.base+'/transactions',headers=self.headers[name],json=body)

    def test_empty_read_does_not_create_or_expose_operator_and_preserves_legacy(self):
        before=self.path.read_bytes()
        for name in self.users:
            for suffix in ['', '/history','/transactions']:
                r=self.client.get(self.base+suffix,headers=self.headers[name]);self.assertEqual(r.status_code,200,r.text)
                self.assertEqual(r.headers['cache-control'],'no-store')
                self.assertEqual(r.json()['holdings'] if suffix=='' else r.json(),[])
                self.assertNotIn('canary',r.text)
        self.assertEqual(self.path.read_bytes(),before)
        with self.connect() as conn:
            initialize_ownership(conn)
            self.assertEqual(pf.summary(conn),self.legacy_summary)
            self.assertEqual(pf.transactions(conn),self.legacy_transactions)
            self.assertEqual(conn.execute('SELECT owner_id FROM stock_groups').fetchone()[0],None)

    def test_member_lifecycle_cross_owner_ids_same_stock_and_derived_history(self):
        a=self.add();b=self.add('b',amount=90)
        self.assertEqual(a.status_code,200,a.text);self.assertEqual(b.status_code,200,b.text)
        aid,bid=a.json()['id'],b.json()['id'];self.assertNotEqual(aid,bid)
        for name,other in [('a',bid),('b',aid)]:
            r=self.client.get(self.base+'/transactions',headers=self.headers[name]);self.assertEqual(len(r.json()),2)
            self.assertNotIn(other,[t['id'] for t in r.json()])
            self.assertFalse({'amount','quantity','note'} & r.json()[0].keys())
            for foreign in [other,99999]:
                self.assertEqual(self.client.delete(self.base+f'/transactions/{foreign}',headers=self.headers[name]).status_code,404)
            self.assertEqual(self.client.get(self.base,headers=self.headers[name]).json()['holdings'][0]['code'],'AAAAAA')
            self.assertTrue(self.client.get(self.base+'/history',headers=self.headers[name]).json())
        self.assertEqual(self.client.delete(self.base+f'/transactions/{aid}',headers=self.headers['a']).status_code,200)
        self.assertEqual(self.client.get(self.base,headers=self.headers['a']).json()['holdings'],[])
        self.assertEqual(len(self.client.get(self.base,headers=self.headers['b']).json()['holdings']),1)
        with self.connect() as conn:
            self.assertEqual(pf.summary(conn),self.legacy_summary)
            self.assertEqual(pf.transactions(conn),self.legacy_transactions)
            self.assertEqual(conn.execute('SELECT note FROM private_records').fetchone()[0],'operator-private-canary')
            for row in conn.execute('SELECT quantity,avg_price FROM stock_group_members'):
                self.assertEqual(tuple(row),(None,None))
        self.assertEqual(self.add('b',stock_code='BBBBBB',price=20,amount=40).status_code,200)
        self.assertEqual(self.client.get(self.base,headers=self.headers['a']).json()['holdings'],[])
        self.assertEqual({h['code'] for h in self.client.get(self.base,headers=self.headers['b']).json()['holdings']},{'AAAAAA','BBBBBB'})

    def test_authority_csrf_spoofing_and_unclassified_paths(self):
        self.assertEqual(self.client.get(self.base).status_code,401)
        self.assertEqual(self.client.get(self.base,headers={'x-user-id':self.users['a']}).status_code,401)
        for field,value in [('Origin','https://attacker.example'),('X-CSRF-Token','invalid')]:
            headers={**self.headers['a'],field:value}
            r=self.client.post(self.base+'/transactions',headers=headers,json={'trade_date':'2026-01-01','kind':'deposit','amount':100})
            self.assertEqual(r.status_code,403)
        for extra in [{'owner_id':self.users['b']},{'group_id':self.legacy_gid}]:
            self.assertEqual(self.add(**extra).status_code,422)
        for path in ['/api/portfolio','/api/portfolio/transactions','/api/spine/groups/1',
                     '/api/spine/search?q=portfolio',self.base+'/exposure',self.base+'/flow',
                     self.base+'/events',self.base+'/principles',self.base+'/thesis',self.base+'/alerts']:
            self.assertEqual(self.client.get(path,headers=self.headers['a']).status_code,404)
        legacy=FastAPI();legacy.include_router(routes.router)
        with TestClient(legacy) as client:self.assertEqual(client.get(self.base).status_code,404)

    def test_failed_add_and_delete_roll_back_group_autofunding_and_members(self):
        self.assertEqual(self.add(kind='sell').status_code,409)
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM stock_groups WHERE owner_id IS NOT NULL').fetchone()[0],0)
            conn.execute("CREATE TRIGGER fail_member BEFORE INSERT ON stock_group_members BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        self.assertEqual(self.add().status_code,503)
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM stock_groups WHERE owner_id IS NOT NULL').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM portfolio_transactions').fetchone()[0],2)
            conn.execute('DROP TRIGGER fail_member')
        self.assertEqual(self.add().status_code,200)
        rows=self.client.get(self.base+'/transactions',headers=self.headers['a']).json()
        deposit=next(r['id'] for r in rows if r['kind']=='deposit')
        self.assertEqual(self.client.delete(self.base+f'/transactions/{deposit}',headers=self.headers['a']).status_code,409)
        self.assertEqual(self.client.get(self.base+'/transactions',headers=self.headers['a']).json(),rows)

    def test_concurrent_first_write_unique_group_and_serialized_ledger(self):
        def write(_):
            service=MemberPortfolio(self.path,self.users['a'])
            return service.add(TransactionCreate(trade_date='2026-01-01',kind='buy',stock_code='AAAAAA',amount=50,price=10))
        with ThreadPoolExecutor(max_workers=4) as pool:ids=list(pool.map(write,range(4)))
        self.assertEqual(len(set(ids)),4)
        with self.connect() as conn:
            groups=conn.execute('SELECT id FROM stock_groups WHERE owner_id=?',(self.users['a'],)).fetchall()
            self.assertEqual(len(groups),1)
            ledger=pf.replay(pf._txs(conn,groups[0][0]))
            self.assertEqual(ledger.cash,0);self.assertEqual(ledger.positions['AAAAAA'].qty,20)
            self.assertEqual(pf.group_id(conn),self.legacy_gid)

    def test_unprepared_schema_fails_closed_and_company_lookup_only_market_fields(self):
        with self.connect() as conn:
            conn.execute("INSERT INTO companies VALUES(NULL,'AAAA 비상장')")
            conn.execute("INSERT INTO companies VALUES('','AAAA 빈코드')")
        r=self.client.get(self.base+'/companies?q=AAAA',headers=self.headers['a'])
        self.assertEqual(r.json(),[{'stock_code':'AAAAAA','corp_name':'가나'}])
        with self.connect() as conn:conn.execute('DROP INDEX idx_portfolio_owner')
        before=self.path.read_bytes()
        r=self.client.get(self.base,headers=self.headers['a'])
        self.assertEqual(r.status_code,503);self.assertNotIn(str(self.path),r.text)
        self.assertEqual(self.add().status_code,503)
        self.assertEqual(self.path.read_bytes(),before)

    def test_invalid_dates_and_nonfinite_money_rejected_without_writes(self):
        before=self.path.read_bytes()
        self.assertEqual(self.add(trade_date='2026-99-99').status_code,422)
        r=self.client.post(self.base+'/transactions',headers={**self.headers['a'],'Content-Type':'application/json'},
            content='{"trade_date":"2026-01-01","kind":"deposit","amount":1e309}')
        self.assertEqual(r.status_code,422)
        self.assertNotIn('input',r.text)
        self.assertEqual(self.add(amount=1e308,price=1e-308).status_code,409)
        self.assertEqual(self.path.read_bytes(),before)
        self.identities.set_enabled(self.users['a'],False)
        self.assertEqual(self.client.get(self.base,headers=self.headers['a']).status_code,401)
        self.assertEqual(self.add().status_code,401)

    def test_legacy_empty_group_selection_never_selects_new_member(self):
        with self.connect() as conn:
            conn.execute('DELETE FROM portfolio_transactions');conn.execute('DELETE FROM stock_group_members');conn.execute('DELETE FROM stock_groups')
        self.assertEqual(self.add().status_code,200)
        with self.connect() as conn:
            legacy=pf.group_id(conn)
            self.assertIsNone(conn.execute('SELECT owner_id FROM stock_groups WHERE id=?',(legacy,)).fetchone()[0])
            self.assertEqual(pf.transactions(conn),[])


if __name__=='__main__':unittest.main()
