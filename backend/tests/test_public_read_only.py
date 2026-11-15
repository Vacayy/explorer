"""Initial public reads need no OAuth/CLI secrets; all privileged paths stay shut."""
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.auth import router
from security.access_boundary import PublicAccessBoundary
from security.publication_store import PublicationStore
from security.public_startup import validate_public_state
from security.login_flow import SESSION_COOKIE
import config

READ_ONLY={'EXPLORER_ACCESS_MODE':'public','EXPLORER_PUBLIC_READ_ONLY':'1',
           'EXPLORER_AUTH_ENABLED':'0','EXPLORER_PUBLIC_ORIGIN':'https://example.test'}


class PublicReadOnlyTests(unittest.TestCase):
    def test_session_and_readers_work_without_auth_while_all_protected_routes_stay_closed(self):
        app=FastAPI();app.include_router(router)
        @app.get('/reader')
        def reader(): return {'ok':True}
        @app.get('/member')
        def member(): raise AssertionError('member executed')
        @app.post('/operator')
        def operator(): raise AssertionError('operator executed')
        @app.get('/api/public/chat/session')
        def trial(): raise AssertionError('trial executed')
        policies={('GET','/reader'):'public',('GET','/member'):'member',
                  ('POST','/operator'):'operator',('GET','/api/public/chat/session'):'trial',
                  ('GET','/api/auth/session'):'auth',('GET','/api/auth/google/start'):'auth',
                  ('GET','/api/auth/google/callback'):'auth',('POST','/api/auth/logout'):'auth'}
        def no_auth():raise AssertionError('authentication storage accessed')
        app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies=policies,service_factory=no_auth)
        with patch.dict(os.environ,READ_ONLY,clear=True), TestClient(app,base_url='https://example.test') as client:
            client.cookies.set(SESSION_COOKIE,'old-or-forged-session')
            headers={'x-user-id':'operator','x-user-role':'operator','origin':'https://example.test'}
            response=client.get('/api/auth/session',headers=headers)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json(),{'authenticated':False,'user':None,'csrf_token':None,
                                             'login_available':False,'chat_available':False})
            self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertEqual(client.get('/reader',headers=headers).json(),{'ok':True})
            for method,path in [('GET','/member'),('POST','/operator'),('GET','/api/public/chat/session'),
                                ('GET','/api/auth/google/start'),('GET','/api/auth/google/callback'),('POST','/api/auth/logout')]:
                r=client.request(method,path,headers=headers);self.assertEqual(r.status_code,503,path)
                self.assertEqual(r.headers['cache-control'],'no-store')

    def test_startup_reads_prepared_stores_without_oauth_or_chat_and_rejects_bad_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);app=root/'app.sqlite';pub=root/'publication.sqlite';macro=root/'macro.sqlite';media=root/'media';media.mkdir()
            with closing(sqlite3.connect(app)) as c:
                c.executescript('CREATE TABLE stock_groups(owner_id); CREATE TABLE portfolio_transactions(group_id);'
                    'CREATE TABLE member_portfolio_principles(group_id,text,rules_json,notes_json);'
                    'CREATE TABLE member_saved_documents(owner_user_id,doc_id,saved_fingerprint,note);'
                    'CREATE TABLE raw_documents(id,markdown,media_json);')
            PublicationStore(pub).initialize()
            with closing(sqlite3.connect(macro)) as c:
                c.executescript("CREATE TABLE meta(key,value);INSERT INTO meta VALUES('schema','public_macro_direct_v1');")
            app.chmod(0o600);macro.chmod(0o600)
            env={**READ_ONLY,'EXPLORER_PUBLICATION_DB':str(pub),'EXPLORER_PUBLIC_MACRO_DB':str(macro)}
            before={p:p.read_bytes() for p in (app,pub,macro)}
            with patch.object(config,'DB_PATH',app),patch.object(config,'MEDIA_PATH',media):
                with patch.dict(os.environ,env,clear=True),patch('security.public_startup.configured_trial',side_effect=AssertionError('chat init')):
                    validate_public_state()
                for changes in [{'EXPLORER_AUTH_ENABLED':'1'}, {'EXPLORER_PUBLIC_READ_ONLY':'invalid'},
                                {'EXPLORER_PUBLIC_READ_ONLY':'0','EXPLORER_AUTH_ENABLED':'1'}]:
                    with patch.dict(os.environ,{**env,**changes},clear=True):
                        with self.assertRaises(RuntimeError):validate_public_state()
                with closing(sqlite3.connect(pub)) as c:
                    c.execute('UPDATE publication_metadata SET version=0');c.commit()
                with patch.dict(os.environ,env,clear=True):
                    with self.assertRaises(RuntimeError):validate_public_state()
            self.assertEqual(app.read_bytes(),before[app]);self.assertEqual(macro.read_bytes(),before[macro])
