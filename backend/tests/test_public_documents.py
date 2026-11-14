"""Publication lifecycle through actual ASGI routes, SQLite and file bytes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import public_documents as routes
from security.access_boundary import PublicAccessBoundary, PUBLIC_ROUTE_POLICIES
from security.identity_store import IdentityStore
from security.login_flow import SESSION_COOKIE, session_csrf
from security.public_documents import PublicDocuments, DocumentUnavailable
from security.publication_store import PublicationStore, PublicationConflict

PNG = b'\x89PNG\r\n\x1a\nfixture-bytes'


class PublicDocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root/'source.sqlite'
        self.media = self.root/'media'; self.media.mkdir()
        (self.media/'image.png').write_bytes(PNG)
        with sqlite3.connect(self.source) as conn:
            conn.executescript('''CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, title, source_type, url, published_at,
                markdown, raw_content, media_json, content_hash, private_note);
                INSERT INTO raw_documents VALUES(1,'Reviewed title','web','https://example.test/source','2026-11-14',
                'Reviewed body',NULL,'["image.png"]','unchanged-markdown-hash','private-canary');
                INSERT INTO raw_documents VALUES(2,'Private title','note',NULL,NULL,'private-canary',NULL,'[]','hash','private-canary');''')
        self.store = PublicationStore(self.root/'publication.sqlite'); self.store.initialize()
        self.service = PublicDocuments(self.source, self.media, self.store)
        identities = IdentityStore(self.root/'identity.sqlite'); identities.initialize()
        user = identities.get_or_create_google_user('accounts.google.com','operator')
        identities.set_role(user.id,'operator'); self.actor = user.id
        token = identities.issue_session(user.id, ttl_seconds=3600)
        member = identities.get_or_create_google_user('accounts.google.com','member')
        member_token = identities.issue_session(member.id, ttl_seconds=3600)
        self.headers = {'Cookie':SESSION_COOKIE+'='+token, 'Origin':'https://beta.example', 'x-csrf-token':session_csrf(token)}
        self.member = {'Cookie':SESSION_COOKIE+'='+member_token}
        self.app = FastAPI(); self.app.include_router(routes.router)
        policies = {k:v for k,v in PUBLIC_ROUTE_POLICIES.items() if k[1].startswith(('/api/public/documents','/api/operator/publications'))}
        self.app.add_middleware(PublicAccessBoundary, routes=self.app.router.routes, policies=policies,
            service_factory=lambda:SimpleNamespace(identities=identities,config=SimpleNamespace(public_origin='https://beta.example')))
        self.client=TestClient(self.app,base_url='https://beta.example'); self.addCleanup(self.client.close)
        p=patch.object(PublicDocuments,'from_environment',return_value=self.service);p.start();self.addCleanup(p.stop)

    def preview(self):
        response=self.client.get('/api/operator/publications/1/preview',headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def approve(self, preview=None):
        preview=preview or self.preview()
        return self.client.post('/api/operator/publications/1/approve',headers=self.headers,
            json={'fingerprint':preview['fingerprint'],'expected_version':preview['version'],
                  'rights_basis':'Synthetic fixture created for this test','personal_data_excluded':True})

    def mutate(self, sql):
        with sqlite3.connect(self.source) as conn: conn.execute(sql)

    def test_lifecycle_operator_review_approve_read_attachment_and_revoke(self):
        source_bytes=self.source.read_bytes()
        for path in ('/api/public/documents/1','/api/public/documents/2','/api/public/documents/999',
                     '/api/public/documents/1/attachments/0','/media/image.png'):
            response=self.client.get(path);self.assertEqual(response.status_code,404)
            self.assertNotIn('canary',response.text)
        preview=self.preview()
        url=preview['attachment_previews'][0]
        self.assertEqual(self.client.get(url).status_code,401)
        self.assertEqual(self.client.get(url,headers=self.member).status_code,403)
        self.assertEqual(self.client.get(url,headers=self.headers).content,PNG)
        self.assertEqual(self.approve(preview).json(),{'id':1,'version':1,'status':'approved'})
        response=self.client.get('/api/public/documents/1')
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('canary',response.text)
        self.assertNotIn(str(self.root),response.text)
        self.assertEqual(response.json()['content'],'Reviewed body')
        attachment=self.client.get(response.json()['attachments'][0]['url'])
        self.assertEqual(attachment.content,PNG)
        self.assertEqual(attachment.headers['content-type'],'image/png')
        self.assertEqual(attachment.headers['x-content-type-options'],'nosniff')
        self.assertEqual(attachment.headers['cache-control'],'no-store')
        self.assertEqual(self.client.get('/api/public/documents/1/attachments/1').status_code,404)
        self.assertEqual(self.client.post('/api/operator/publications/1/revoke',headers=self.headers,json={'expected_version':1}).json()['version'],2)
        for path in ('/api/public/documents/1','/api/public/documents/1/attachments/0'):
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.approve(preview).status_code,409)
        self.assertEqual(self.approve().status_code,200)
        self.assertEqual(self.source.read_bytes(),source_bytes)
        self.assertEqual(self.store.get(1)['approved_by'],self.actor)

    def test_public_list_search_pagination_and_content_changes(self):
        path='/api/public/documents'
        self.assertEqual(self.client.get(path).json(),{'items':[],'next_cursor':None})
        self.assertEqual(self.approve().status_code,200)
        with sqlite3.connect(self.source) as conn:
            for id in [3,4]:
                conn.execute('INSERT INTO raw_documents VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (id,f'Public title {id}','web',None,None,f'Searchable body {id}',None,'[]','same','private-canary'))
        for id in [3,4]:
            preview=self.service.preview(id)
            self.store.approve(id,preview['fingerprint'],0,self.actor,'Synthetic fixture')
        source_bytes=self.source.read_bytes()
        r=self.client.get(path+'?limit=1');self.assertEqual(r.status_code,200)
        self.assertEqual([i['id'] for i in r.json()['items']],[4]);self.assertIsInstance(r.json()['next_cursor'],str)
        self.assertEqual([i['id'] for i in self.client.get(path,params={'limit':1,'cursor':r.json()['next_cursor']}).json()['items']],[3])
        result=self.client.get(path+'?q=SEARCHABLE').json()
        self.assertEqual([i['id'] for i in result['items']],[4,3])
        self.assertNotIn('total',result);self.assertNotIn('canary',str(result))
        self.assertTrue(all(len(i['snippet'])<=240 for i in result['items']))
        self.assertEqual(self.client.get(path+'?q=private-canary').json()['items'],[])
        self.assertEqual(self.source.read_bytes(),source_bytes)
        self.store.revoke(4,1,self.actor)
        self.mutate("UPDATE raw_documents SET title='changed-private-title' WHERE id=3")
        self.assertEqual([i['id'] for i in self.client.get(path).json()['items']],[1])
        self.assertNotIn('changed-private-title',self.client.get(path).text)
        (self.media/'image.png').write_bytes(PNG+b'changed')
        self.assertEqual(self.client.get(path).json()['items'],[])
        for query in ['?limit=0','?limit=21','?q='+'x'*121]:
            self.assertEqual(self.client.get(path+query).status_code,422)

    def test_list_rechecks_earlier_approval_and_never_false_empty_on_budget(self):
        from security.public_documents import ReadBudget
        self.assertEqual(self.approve().status_code,200)
        with patch('security.public_documents.ReadBudget',return_value=ReadBudget(remaining=1)):
            self.assertEqual(self.client.get('/api/public/documents').status_code,503)
        with sqlite3.connect(self.source) as conn:
            conn.execute("INSERT INTO raw_documents VALUES(3,'Third','web',NULL,NULL,'Third body',NULL,'[]','hash',NULL)")
        self.store.approve(3,self.service.preview(3)['fingerprint'],0,self.actor,'Fixture')
        with patch('security.public_documents.ReadBudget',return_value=ReadBudget(remaining=20)):
            limited=self.client.get('/api/public/documents').json()
        self.assertEqual([i['id'] for i in limited['items']],[3])
        continued=self.client.get('/api/public/documents',params={'cursor':limited['next_cursor']}).json()
        self.assertEqual([i['id'] for i in continued['items']],[1])
        original=self.service.published
        def revoke_earlier(id,*args,**kwargs):
            result=original(id,*args,**kwargs)
            if id==1:self.store.revoke(3,1,self.actor)
            return result
        with patch.object(self.service,'published',side_effect=revoke_earlier):
            result=self.client.get('/api/public/documents').json()
        self.assertEqual([i['id'] for i in result['items']],[1])

    def test_search_continues_past_nonmatches_and_changed_approvals(self):
        with sqlite3.connect(self.source) as conn:
            conn.executemany('INSERT INTO raw_documents VALUES(?,?,?,?,?,?,?,?,?,?)',[
                (id,f'Title {id}','web',None,None,'needle' if id==3 else 'unrelated',None,'[]','hash',None)
                for id in range(3,104)])
        for id in range(3,104):
            self.store.approve(id,self.service.preview(id)['fingerprint'],0,self.actor,'Fixture')
        for changed in [False,True]:
            if changed:self.mutate("UPDATE raw_documents SET markdown='changed-private-canary' WHERE id>3")
            first=self.client.get('/api/public/documents',params={'q':'needle'}).json()
            self.assertEqual(first['items'],[]);self.assertIsInstance(first['next_cursor'],str)
            self.assertNotIn('canary',str(first))
            second=self.client.get('/api/public/documents',params={'q':'needle','cursor':first['next_cursor']})
            self.assertEqual(second.status_code,200,second.text)
            self.assertEqual([i['id'] for i in second.json()['items']],[3])
            self.assertIsNone(second.json()['next_cursor'])

    def test_cursor_integrity_query_binding_expiry_restart_and_explicit_upgrade(self):
        from contextlib import closing
        from security.publication_store import InvalidCursor
        import json
        import subprocess
        import sys
        key=self.store.cursor_cipher()
        token=self.store.encode_cursor(23,'query')
        fresh=PublicationStore(self.store.path)
        self.assertEqual(fresh.decode_cursor(token,'query'),23)
        fresh.initialize()  # Provisioning again must not rotate the key.
        self.assertEqual(fresh.decode_cursor(token,'query'),23)
        restored_path=self.root/'restored-publication.sqlite'
        with self.store.connection(readonly=True) as source, closing(sqlite3.connect(restored_path)) as restored:
            source.backup(restored)
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        # A separate interpreter opens the restored SQLite and resumes the search.
        result=subprocess.run([sys.executable,'-c',
            'import sys; from pathlib import Path; from security.publication_store import PublicationStore; '
            'assert PublicationStore(Path(sys.argv[1])).decode_cursor(sys.stdin.read(),"query")==23',
            str(restored_path)],input=token,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for cursor,q in [(token,'other'),(token[:-10]+'AAAAAAAAAA','query'),('invalid','query'),
                         (key.encrypt_at_time(json.dumps({'v':1,'before':23,'q':'query'}).encode(),current_time=1).decode(),'query')]:
            self.assertEqual(self.client.get('/api/public/documents',params={'cursor':cursor,'q':q}).status_code,400)
        # Older v1 stores require explicit preparation; request never upgrades.
        with sqlite3.connect(self.store.path) as conn:
            conn.execute('ALTER TABLE publication_metadata DROP COLUMN cursor_key')
            conn.execute('UPDATE publication_metadata SET version=1')
        before=self.store.path.read_bytes()
        self.assertEqual(self.client.get('/api/public/documents',params={'cursor':token,'q':'query'}).status_code,503)
        self.assertEqual(self.client.get('/api/public/documents').status_code,503)
        self.assertEqual(self.store.path.read_bytes(),before)
        fresh.initialize()
        self.assertEqual(fresh.decode_cursor(fresh.encode_cursor(23,'query'),'query'),23)
        with self.assertRaises(InvalidCursor):fresh.decode_cursor(token,'query')

    def test_query_cannot_probe_changed_body_via_attachment_budget(self):
        from security.public_documents import ReadBudget
        self.assertEqual(self.approve().status_code,200)
        self.mutate("UPDATE raw_documents SET markdown='secret-canary' WHERE id=1")
        statuses=[]
        for query in ['secret','absent']:
            with patch('security.public_documents.ReadBudget',return_value=ReadBudget(remaining=15)):
                statuses.append(self.client.get('/api/public/documents',params={'q':query}).status_code)
        self.assertEqual(statuses,[503,503])

    def test_no_operator_impersonation_or_csrf_bypass(self):
        preview=self.preview()
        body={'fingerprint':preview['fingerprint'],'expected_version':0,'rights_basis':'fixture','personal_data_excluded':True}
        for headers,status in [({},401),({'x-user-role':'operator'},401),(self.member,403),
                               ({'Cookie':self.headers['Cookie']},403),({**self.headers,'Origin':'https://evil.test'},403)]:
            self.assertEqual(self.client.post('/api/operator/publications/1/approve',headers=headers,json=body).status_code,status)
        body['personal_data_excluded']=False
        self.assertEqual(self.client.post('/api/operator/publications/1/approve',headers=self.headers,json=body).status_code,422)
        self.assertIsNone(self.store.get(1))
        legacy=FastAPI();legacy.include_router(routes.router)
        with TestClient(legacy) as client:
            self.assertEqual(client.get('/api/operator/publications/1/preview',headers=self.headers).status_code,404)

    def test_body_metadata_and_media_change_do_not_inherit_approval(self):
        for sql in ("UPDATE raw_documents SET title='changed' WHERE id=1",
                    "UPDATE raw_documents SET markdown='changed body' WHERE id=1",
                    "UPDATE raw_documents SET published_at='2026-11-15' WHERE id=1",
                    "UPDATE raw_documents SET media_json='[]' WHERE id=1"):
            preview=self.preview();self.assertEqual(self.approve(preview).status_code,200)
            self.mutate(sql)
            self.assertEqual(self.client.get('/api/public/documents/1').status_code,404)
            self.assertEqual(self.approve(preview).status_code,409)

    def test_replaced_file_and_preview_file_fingerprint_are_rejected(self):
        preview=self.preview();self.assertEqual(self.approve(preview).status_code,200)
        (self.media/'image.png').write_bytes(PNG+b'changed')
        for path in ('/api/public/documents/1','/api/public/documents/1/attachments/0',preview['attachment_previews'][0]):
            self.assertEqual(self.client.get(path,headers=self.headers).status_code,404)

    def test_revoke_during_capture_is_rechecked_and_returned_bytes_are_pinned(self):
        self.assertEqual(self.approve().status_code,200)
        original=self.service.capture
        def revoke(*args):
            result=original(*args);self.store.revoke(1,1,self.actor);return result
        with patch.object(self.service,'capture',side_effect=revoke):
            self.assertEqual(self.client.get('/api/public/documents/1').status_code,404)
        self.assertEqual(self.approve().status_code,200)
        def replace(*args):
            result=original(*args);(self.media/'image.png').write_bytes(PNG+b'changed');return result
        with patch.object(self.service,'capture',side_effect=replace):
            self.assertEqual(self.client.get('/api/public/documents/1/attachments/0').content,PNG)
        self.assertEqual(self.client.get('/api/public/documents/1/attachments/0').status_code,404)

    def test_paths_symlinks_types_and_limits_fail_closed(self):
        outside=self.root/'outside.png';outside.write_bytes(PNG)
        (self.media/'link.png').symlink_to(outside)
        (self.media/'linked').symlink_to(self.root,target_is_directory=True)
        for path in ('../outside.png',str(outside),'link.png','linked/outside.png','a/../image.png'):
            import json
            with sqlite3.connect(self.source) as conn: conn.execute('UPDATE raw_documents SET media_json=? WHERE id=1',(json.dumps([path]),))
            self.assertEqual(self.client.get('/api/operator/publications/1/preview',headers=self.headers).status_code,404)
        self.mutate("UPDATE raw_documents SET media_json='[\"image.png\"]' WHERE id=1")
        (self.media/'image.png').write_bytes(b'<html>private-canary</html>')
        self.assertEqual(self.client.get('/api/operator/publications/1/preview',headers=self.headers).status_code,404)
        (self.media/'image.png').write_bytes(PNG)
        with patch('security.public_documents.MAX_FILE',4):
            self.assertEqual(self.client.get('/api/operator/publications/1/preview',headers=self.headers).status_code,404)

    def test_pdf_download_unrelated_store_and_concurrent_approvals(self):
        (self.media/'image.png').write_bytes(b'%PDF-1.7\nfixture')
        preview=self.preview()
        def attempt():
            try:return self.store.approve(1,preview['fingerprint'],0,self.actor,'fixture')['status']
            except PublicationConflict:return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(lambda _:attempt(),range(2))),['approved','conflict'])
        response=self.client.get('/api/public/documents/1/attachments/0')
        self.assertEqual(response.headers['content-type'],'application/pdf')
        self.assertTrue(response.headers['content-disposition'].startswith('attachment;'))
        before=self.source.read_bytes()
        with self.assertRaises(ValueError):PublicationStore(self.source).initialize()
        self.assertEqual(self.source.read_bytes(),before)

    def test_missing_store_and_source_errors_do_not_leak_paths(self):
        self.store.path.unlink()
        response=self.client.get('/api/public/documents/1')
        self.assertEqual(response.status_code,503)
        self.assertNotIn(str(self.root),response.text)
        self.assertFalse(self.store.path.exists())
