"""Actual publication and authentication boundary; synthetic owner-only storage."""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import member_saved as routes
from security.access_boundary import PublicAccessBoundary, PUBLIC_ROUTE_POLICIES
from security.identity_store import IdentityStore
from security.login_flow import SESSION_COOKIE, session_csrf
from security.member_saved import initialize_member_saved
from security.public_documents import PublicDocuments, ReadBudget
from security.publication_store import PublicationStore


class MemberSavedTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.source=self.root/'source.sqlite'
        with closing(sqlite3.connect(self.source)) as conn, conn:
            conn.executescript('''CREATE TABLE raw_documents(id INTEGER PRIMARY KEY,title,source_type,url,published_at,
                markdown,raw_content,media_json);
                CREATE TABLE saved_items(id, title, note);
                INSERT INTO saved_items VALUES(1,'LEGACY_CANARY','PRIVATE_NOTE');''')
            conn.executemany('INSERT INTO raw_documents VALUES(?,?,?,NULL,NULL,?,NULL,?)',
                [(i,f'Document {i}','web','Published content','[]') for i in range(1,203)])
            initialize_member_saved(conn)
        self.store=PublicationStore(self.root/'publication.sqlite');self.store.initialize()
        self.docs=PublicDocuments(self.source,self.root,self.store)
        for i in range(1,203):
            snap=self.docs.capture(i)
            self.store.approve(i,snap.fingerprint,0,'operator','Synthetic test source')
        identities=IdentityStore(self.root/'identity.sqlite');identities.initialize()
        self.headers={};self.users={}
        for name in ('a','b'):
            user=identities.get_or_create_google_user('accounts.google.com',name)
            self.users[name]=user.id
            token=identities.issue_session(user.id,ttl_seconds=3600)
            self.headers[name]={'Cookie':SESSION_COOKIE+'='+token,'Origin':'https://beta.example','X-CSRF-Token':session_csrf(token)}
        app=FastAPI();app.include_router(routes.router)
        policies={k:v for k,v in PUBLIC_ROUTE_POLICIES.items() if k[1].startswith('/api/member/saved')}
        app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies=policies,
            service_factory=lambda:SimpleNamespace(identities=identities,config=SimpleNamespace(public_origin='https://beta.example')))
        self.client=TestClient(app,base_url='https://beta.example');self.addCleanup(self.client.close)
        for p in (patch('config.DB_PATH',self.source),patch.object(PublicDocuments,'from_environment',return_value=self.docs)):
            p.start();self.addCleanup(p.stop)
        self.base='/api/member/saved'

    def add(self,doc=1,owner='a',**extra):
        return self.client.post(self.base,headers=self.headers[owner],json={'doc_id':doc,**extra})

    def listing(self,owner='a',suffix=''):
        return self.client.get(self.base+suffix,headers=self.headers[owner])

    def test_owner_isolation_idempotency_filter_and_legacy_unchanged(self):
        before=self.source.read_bytes()
        self.assertEqual(self.listing().json(),{'items':[],'next_offset':None})
        self.assertEqual(self.source.read_bytes(),before)
        a=self.add(note='Only A');b=self.add(owner='b',note='Only B')
        self.assertEqual(a.status_code,201,a.text);self.assertEqual(b.status_code,201,b.text)
        aid=a.json()['id'];bid=b.json()['id'];self.assertNotEqual(aid,bid)
        self.assertEqual(self.add(note='Overwrite attempt').json()['note'],'Only A')
        item=self.listing(suffix='?doc_id=1').json()['items'][0]
        self.assertEqual((item['title'],item['url'],item['available']),('Document 1','/doc/1',True))
        self.assertEqual(self.listing(suffix='?doc_id=2').json()['items'],[])
        for method,body in [('patch',{'note':'stolen'}),('delete',None)]:
            kwargs={'headers':self.headers['a']}
            if body is not None:kwargs['json']=body
            self.assertEqual(getattr(self.client,method)(f'{self.base}/{bid}',**kwargs).status_code,404)
        self.assertNotIn('Only B',self.listing().text)
        self.assertEqual(self.client.patch(f'{self.base}/{aid}',headers=self.headers['a'],json={'note':'Edited'}).status_code,200)
        self.assertEqual(self.listing().json()['items'][0]['note'],'Edited')
        with closing(sqlite3.connect(self.source)) as conn, conn:
            self.assertEqual(conn.execute('SELECT * FROM saved_items').fetchall(),[(1,'LEGACY_CANARY','PRIVATE_NOTE')])
            columns=[r[1] for r in conn.execute('PRAGMA table_info(member_saved_documents)')]
            self.assertFalse({'title','url','content'} & set(columns))

    def test_revocation_change_delete_preserve_notes_and_management(self):
        ident=self.add(note='Keep my note').json()['id']
        with closing(sqlite3.connect(self.source)) as conn, conn:conn.execute("UPDATE raw_documents SET title='Changed private title' WHERE id=1")
        item=self.listing().json()['items'][0]
        self.assertEqual((item['available'],item['title'],item['url'],item['note']),(False,None,None,'Keep my note'))
        self.assertEqual(self.add().status_code,404)
        with closing(sqlite3.connect(self.source)) as conn, conn:conn.execute('DELETE FROM raw_documents WHERE id=1')
        self.assertFalse(self.listing().json()['items'][0]['available'])
        with patch.object(PublicDocuments,'from_environment',side_effect=ValueError('offline')):
            self.assertEqual(self.client.patch(f'{self.base}/{ident}',headers=self.headers['a'],json={'note':'Still mine'}).status_code,200)
            self.assertEqual(self.client.delete(f'{self.base}/{ident}',headers=self.headers['a']).status_code,200)
        self.add(2)
        self.store.revoke(2,1,'operator')
        self.assertFalse(self.listing().json()['items'][0]['available'])
        self.assertEqual(self.add(2).status_code,404)

    def test_budget_storage_errors_uninitialized_and_no_get_ddl(self):
        self.add()
        before=self.source.read_bytes()
        with patch('security.member_saved.ReadBudget',return_value=ReadBudget(0)):
            self.assertEqual(self.listing().status_code,503)
        self.assertEqual(self.source.read_bytes(),before)
        self.add(2)
        # One budget covers the complete page, not one independent budget per item.
        with patch('security.member_saved.ReadBudget',return_value=ReadBudget(len('Published content'))):
            self.assertEqual(self.listing().status_code,503)
        with patch.object(self.docs,'published',side_effect=sqlite3.OperationalError('secret path')):
            r=self.listing();self.assertEqual(r.status_code,503);self.assertNotIn('secret path',r.text)
        from security.public_documents import DocumentUnavailable
        failure=DocumentUnavailable();failure.__cause__=PermissionError(13,'private path')
        with patch.object(self.docs,'published',side_effect=failure):
            self.assertEqual(self.listing().status_code,503)
        with closing(sqlite3.connect(self.source)) as conn, conn:conn.execute('DROP TABLE member_saved_documents')
        before=self.source.read_bytes()
        self.assertEqual(self.listing().status_code,503)
        self.assertEqual(self.add().status_code,503)
        self.assertEqual(self.source.read_bytes(),before)

    def test_auth_csrf_forged_fields_limits_and_no_store(self):
        self.assertEqual(self.client.get(self.base).status_code,401)
        bad={k:v for k,v in self.headers['a'].items() if k!='X-CSRF-Token'}
        self.assertEqual(self.client.post(self.base,headers=bad,json={'doc_id':1}).status_code,403)
        for extra in ({'title':'FORGED_SECRET'},{'url':'https://evil.test'},{'owner_user_id':self.users['b']},{'note':'n'*2001}):
            r=self.add(**extra);self.assertEqual(r.status_code,422,r.text);self.assertNotIn('FORGED_SECRET',r.text)
        self.assertEqual(self.listing(suffix='?limit=21').status_code,422)
        self.assertEqual(self.listing().headers['cache-control'],'no-store')
        with closing(sqlite3.connect(self.source)) as conn, conn:
            conn.executemany('INSERT INTO member_saved_documents(owner_user_id,doc_id,saved_fingerprint) VALUES(?,?,?)',[(self.users['a'],i,self.docs.capture(i).fingerprint) for i in range(1,201)])
        first=self.listing().json();self.assertEqual(len(first['items']),20);self.assertEqual(first['next_offset'],20)
        self.assertEqual(self.listing(suffix='?offset=180').json()['next_offset'],None)
        self.assertEqual(self.add(201).status_code,409)
        self.assertEqual(self.add(1).status_code,201)
        self.assertEqual(self.add(201,owner='b').status_code,201)

    def test_revocation_during_later_validation_clears_earlier_metadata(self):
        self.add(1,note='one');self.add(2,note='two')
        original=self.docs.published
        def during(doc_id,**kwargs):
            result=original(doc_id,**kwargs)
            if doc_id==1:self.store.revoke(2,1,'operator')
            return result
        with patch.object(self.docs,'published',side_effect=during):
            items=self.listing().json()['items']
        self.assertFalse(items[0]['available']);self.assertIsNone(items[0]['title'])
        self.assertEqual(items[0]['note'],'two')

    def reapprove(self,doc_id):
        record=self.store.get(doc_id)
        self.store.approve(doc_id,self.docs.capture(doc_id).fingerprint,record['version'],'operator','Synthetic test source')

    def test_saved_fingerprint_survives_reapproval_and_idempotent_post(self):
        first=self.add(note='Original note').json()
        self.assertEqual(first['status'],'available');self.assertIsNone(first['current_url'])
        original=self.docs.capture(1).fingerprint
        self.store.revoke(1,1,'operator');self.reapprove(1)
        self.assertEqual(self.listing().json()['items'][0]['status'],'available')
        with closing(sqlite3.connect(self.source)) as conn,conn:
            conn.execute("UPDATE raw_documents SET markdown='New public version',title='New title' WHERE id=1")
        unapproved=self.listing().json()['items'][0]
        self.assertEqual(unapproved['status'],'unavailable');self.assertIsNone(unapproved['current_url'])
        self.reapprove(1)
        changed=self.listing().json()['items'][0]
        self.assertEqual((changed['status'],changed['available'],changed['title'],changed['url'],changed['current_url']),
                         ('changed',False,None,None,'/doc/1'))
        again=self.add(note='Do not replace').json()
        self.assertEqual(again['status'],'changed');self.assertEqual(again['note'],'Original note')
        with closing(sqlite3.connect(self.source)) as conn:
            self.assertEqual(conn.execute('SELECT saved_fingerprint FROM member_saved_documents').fetchone()[0],original)
        self.store.revoke(1,self.store.get(1)['version'],'operator')
        revoked=self.listing().json()['items'][0]
        self.assertEqual(revoked['status'],'unavailable');self.assertIsNone(revoked['current_url'])

    def test_attachment_only_change_and_mid_page_changed_revocation(self):
        attachment=self.root/'image.png';attachment.write_bytes(b'\x89PNG\r\n\x1a\noriginal')
        with closing(sqlite3.connect(self.source)) as conn,conn:
            conn.execute('UPDATE raw_documents SET media_json=? WHERE id=2',('["image.png"]',))
        self.reapprove(2)
        self.add(1);self.add(2,note='Attachment version')
        attachment.write_bytes(b'\x89PNG\r\n\x1a\nchanged')
        self.assertEqual(self.listing().json()['items'][0]['status'],'unavailable')
        self.reapprove(2)
        self.assertEqual(self.listing().json()['items'][0]['status'],'changed')
        original=self.docs.published
        def during(doc_id,**kwargs):
            result=original(doc_id,**kwargs)
            if doc_id==1:self.store.revoke(2,self.store.get(2)['version'],'operator')
            return result
        with patch.object(self.docs,'published',side_effect=during):
            item=self.listing().json()['items'][0]
        self.assertEqual((item['status'],item['available'],item['title'],item['url'],item['current_url']),
                         ('unavailable',False,None,None,None))
        self.assertEqual(item['note'],'Attachment version')
