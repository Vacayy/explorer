from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import logging
from pathlib import Path
import secrets
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.auth import get_service, router
from security.google_identity import GoogleIdentity
from security.identity_store import IdentityStore
from security.login_flow import (AuthConfig, CallbackQueryFilter, LoginFlow, CALLBACK_PATH,
                                 LOGIN_COOKIE, SESSION_COOKIE, session_csrf, validate_origin,
                                 exchange_google_code)
from security.login_transactions import InvalidLogin, LoginTransactions, safe_return_path


class AuthFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.now = 1000
        self.config = AuthConfig('client', 'secret-test', 'https://example.test', root/'identity.sqlite', root/'login.sqlite')
        self.ids = IdentityStore(self.config.identity_db, clock=lambda: self.now)
        self.tx = LoginTransactions(self.config.login_db, clock=lambda: self.now)
        self.ids.initialize()
        self.tx.initialize()
        self.exchanges = []
        self.verified = []
        def exchange(code, *, config, verifier):
            self.exchanges.append((code, verifier))
            return 'offline-id-token'
        def verify(token, *, client_id, expected_nonce):
            self.verified.append((token, client_id, expected_nonce))
            return GoogleIdentity('https://accounts.google.com', 'google-user')
        self.flow = LoginFlow(self.config, self.ids, self.tx, exchange=exchange, verify=verify)
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[get_service] = lambda: self.flow
        self.client = TestClient(self.app, base_url='https://example.test', follow_redirects=False)
        self.addCleanup(self.client.close)

    def start(self, return_to='/'):
        response = self.client.get('/api/auth/google/start', params={'return_to': return_to})
        self.assertEqual(response.status_code, 303)
        return parse_qs(urlsplit(response.headers['location']).query), response

    def callback(self, params):
        return self.client.get(CALLBACK_PATH, params={'code': 'offline-code', 'state': params['state'][0]})

    def test_success_rotation_pkce_nonce_and_headers(self):
        old_user = self.ids.get_or_create_google_user('accounts.google.com', 'old-user')
        old = self.ids.issue_session(old_user.id, ttl_seconds=60)
        self.client.cookies.set(SESSION_COOKIE, old, domain='example.test', path='/')
        params, start = self.start('/portfolio?tab=history')
        self.assertEqual(params['code_challenge_method'], ['S256'])
        response = self.callback(params)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/portfolio?tab=history')
        self.assertIsNone(self.ids.resolve_session(old))
        new = self.client.cookies.get(SESSION_COOKIE)
        self.assertNotEqual(old, new)
        self.assertIsNotNone(self.ids.resolve_session(new))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.exchanges[0][1].encode()).digest()).decode().rstrip('=')
        self.assertEqual(params['code_challenge'], [challenge])
        self.assertEqual(self.verified[0][2], params['nonce'][0])
        for r in (start, response):
            self.assertEqual(r.headers['cache-control'], 'no-store')
            self.assertEqual(r.headers['referrer-policy'], 'no-referrer')
            cookies = r.headers.get_list('set-cookie')
            self.assertTrue(all('Secure' in c and 'HttpOnly' in c and 'SameSite=lax' in c and 'Path=/' in c and 'Domain=' not in c for c in cookies))
        session = self.client.get('/api/auth/session')
        self.assertEqual(session.json()['user']['role'], 'member')
        self.assertEqual(session.json()['csrf_token'], session_csrf(new))
        self.assertEqual(self.callback(params).status_code, 400)
        self.assertEqual(len(self.exchanges), 1)

    def test_wrong_binding_and_expiry(self):
        params, _ = self.start()
        correct = self.client.cookies.get(LOGIN_COOKIE)
        self.client.cookies.set(LOGIN_COOKIE, secrets.token_urlsafe(32), domain='example.test', path='/')
        self.assertEqual(self.callback(params).status_code, 400)
        self.assertEqual(self.exchanges, [])
        self.client.cookies.set(LOGIN_COOKIE, correct, domain='example.test', path='/')
        self.now += 300
        self.assertEqual(self.callback(params).status_code, 400)
        self.assertEqual(self.exchanges, [])

    def test_invalid_google_disabled_and_provider_error_safe(self):
        def bad_verify(*args, **kwargs):
            raise ValueError('private-provider-details')
        self.flow.verify = bad_verify
        params, _ = self.start()
        response = self.callback(params)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('private-provider', response.text)
        self.assertIsNone(self.client.cookies.get(SESSION_COOKIE))
        user = self.ids.get_or_create_google_user('accounts.google.com', 'disabled-user')
        self.ids.set_enabled(user.id, False)
        self.flow.verify = lambda *a, **kw: GoogleIdentity('accounts.google.com', 'disabled-user')
        params, _ = self.start()
        self.assertEqual(self.callback(params).status_code, 400)
        params, _ = self.start()
        response = self.client.get(CALLBACK_PATH, params={'error':'private-text', 'state':params['state'][0]})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('private-text', response.text)

    def test_logout_requires_origin_and_csrf_and_expired_session(self):
        params, _ = self.start()
        self.callback(params)
        token = self.client.cookies.get(SESSION_COOKIE)
        csrf = self.client.get('/api/auth/session').json()['csrf_token']
        for headers in ({}, {'origin':'https://other.test','x-csrf-token':csrf},
                        {'origin':'https://example.test'}, {'origin':'https://example.test','x-csrf-token':'wrong'}):
            response = self.client.post('/api/auth/logout', headers=headers)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertIsNotNone(self.ids.resolve_session(token))
        response = self.client.post('/api/auth/logout', headers={'origin':'https://example.test', 'x-csrf-token':csrf})
        self.assertEqual(response.json(), {'ok':True})
        self.assertIsNone(self.ids.resolve_session(token))
        self.assertEqual(self.client.get('/api/auth/session').json(), {'authenticated':False,'user':None,'csrf_token':None})
        user = self.ids.get_or_create_google_user('accounts.google.com', 'short-session')
        self.client.cookies.set(SESSION_COOKIE, self.ids.issue_session(user.id, ttl_seconds=1), domain='example.test', path='/')
        self.now += 1
        self.assertFalse(self.client.get('/api/auth/session').json()['authenticated'])

    def test_unsafe_returns_and_origins(self):
        for value in ['https://evil.test','//evil.test','/\\evil.test','/%2f%2fevil.test', '/%255cevil.test','/\nlocation:bad']:
            with self.assertRaises(ValueError):
                safe_return_path(value)
            self.assertEqual(self.client.get('/api/auth/google/start', params={'return_to':value}).status_code, 400)
        for value in ['http://example.test','https://user:pw@example.test','https://example.test/x',
                      'https://example.test?x=y','https://example.test#x','https://example.test\x00','https://exa%6dple.test']:
            with self.assertRaises(ValueError):
                validate_origin(value)
        self.assertNotIn('secret-test', repr(self.config))

    def test_concurrent_single_consume_and_hash_storage(self):
        state, binding, tx = self.tx.create('/safe')
        with self.tx.connection() as conn:
            dump = '\n'.join(conn.iterdump())
        self.assertNotIn(state, dump)
        self.assertNotIn(binding, dump)
        def consume(_):
            try:
                return self.tx.consume(state, binding)
            except InvalidLogin:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = [v for v in pool.map(consume, range(16)) if v]
        self.assertEqual(results, [tx])

    def test_disabled_or_missing_config_creates_no_database(self):
        self.app.dependency_overrides.clear()
        missing = Path(self.tmp.name)/'not-created'
        env = {'EXPLORER_AUTH_ENABLED':'1','EXPLORER_GOOGLE_CLIENT_ID':'client',
               'EXPLORER_GOOGLE_CLIENT_SECRET':'secret', 'EXPLORER_PUBLIC_ORIGIN':'https://example.test',
               'EXPLORER_IDENTITY_DB':str(missing/'identity.sqlite'), 'EXPLORER_LOGIN_DB':str(missing/'login.sqlite')}
        for config in ({}, {'EXPLORER_AUTH_ENABLED':'1'}, env, {**env,'EXPLORER_PUBLIC_ORIGIN':'http://bad'}):
            with patch.dict('os.environ', config, clear=True):
                response = self.client.get('/api/auth/session')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertFalse(missing.exists())

    def test_transaction_provisioning_and_callback_log_filter(self):
        path = Path(self.tmp.name)/'new.sqlite'
        store = LoginTransactions(path)
        self.assertFalse(path.exists())
        with self.assertRaises(sqlite3.OperationalError):
            store.create()
        self.assertFalse(path.exists())
        store.initialize()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        other = Path(self.tmp.name)/'other.sqlite'
        with sqlite3.connect(other) as conn:
            conn.execute('CREATE TABLE existing (id INTEGER)')
        other.chmod(0o644)
        before = other.read_bytes()
        with self.assertRaises(ValueError):
            LoginTransactions(other).initialize()
        self.assertEqual(other.read_bytes(), before)
        self.assertEqual(stat.S_IMODE(other.stat().st_mode), 0o644)
        filter = CallbackQueryFilter()
        record = logging.LogRecord('uvicorn.access',20,'',1,'%s %s %s %s %s',
                                   ('ip','GET',CALLBACK_PATH+'?code=secret&state=secret','1.1',303),None)
        self.assertTrue(filter.filter(record))
        self.assertNotIn('secret', record.getMessage())
        self.assertIn(CALLBACK_PATH, record.getMessage())
        other_record = logging.LogRecord('uvicorn.access',20,'',1,'%s %s %s %s %s',
                                   ('ip','GET','/api/public?sort=date','1.1',200),None)
        filter.filter(other_record)
        self.assertIn('?sort=date', other_record.getMessage())

    def test_exchange_fixed_endpoint_pkce_timeout_and_safe_failure(self):
        with patch('security.login_flow.httpx.Client') as client:
            response = client.return_value.__enter__.return_value.post.return_value
            response.json.return_value = {'id_token':'identity-only', 'access_token':'not-retained', 'refresh_token':'not-retained'}
            token = exchange_google_code('code', config=self.config, verifier='pkce')
            self.assertEqual(token, 'identity-only')
            client.assert_called_once_with(timeout=10, follow_redirects=False, trust_env=False)
            args, kwargs = client.return_value.__enter__.return_value.post.call_args
            self.assertEqual(args, ('https://oauth2.googleapis.com/token',))
            self.assertEqual(kwargs['data']['code_verifier'], 'pkce')
            self.assertEqual(kwargs['data']['redirect_uri'], 'https://example.test' + CALLBACK_PATH)
            response.raise_for_status.side_effect = ValueError('provider-private-content')
            with self.assertRaises(InvalidLogin) as caught:
                exchange_google_code('code', config=self.config, verifier='pkce')
            self.assertNotIn('provider-private', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
