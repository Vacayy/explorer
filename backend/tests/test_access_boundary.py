"""Real ASGI requests and temporary identity DB; no operational data or providers."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.staticfiles import StaticFiles

from security.access_boundary import PublicAccessBoundary, configure_access_boundary
from security.identity_store import IdentityStore
from security.login_flow import SESSION_COOKIE, session_csrf


class AccessBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = 1000
        self.store = IdentityStore(self.root / 'identity.sqlite', clock=lambda: self.now)
        self.store.initialize()
        self.a = self.store.get_or_create_google_user('accounts.google.com', 'a')
        self.b = self.store.get_or_create_google_user('accounts.google.com', 'b')
        self.token = self.store.issue_session(self.a.id, ttl_seconds=60)
        self.service = SimpleNamespace(identities=self.store, config=SimpleNamespace(public_origin='https://beta.example'))
        self.calls = []
        self.app = FastAPI()

        @self.app.get('/public')
        def public():
            return {'market': 'fixture'}

        @self.app.get('/me')
        def me(request: Request):
            self.calls.append('me')
            return {'id': request.state.principal.id}

        @self.app.post('/me')
        def write(request: Request):
            self.calls.append('write')
            return {'id': request.state.principal.id}

        @self.app.get('/operator')
        def operator():
            self.calls.append('operator')
            return {'ok': True}

        @self.app.get('/unclassified')
        def unknown():
            self.calls.append('unclassified')
            return {'private': 'canary'}

        (self.root / 'private.txt').write_text('private-file-canary')
        self.app.mount('/media', StaticFiles(directory=self.root), name='media')
        self.app.add_middleware(PublicAccessBoundary, routes=self.app.router.routes,
            policies={('GET', '/public'): 'public', ('GET', '/me'): 'member',
                      ('POST', '/me'): 'member', ('GET', '/operator'): 'operator'},
            service_factory=lambda: self.service)
        self.client = TestClient(self.app, base_url='https://beta.example')
        self.addCleanup(self.client.close)

    def cookie(self, token=None):
        return {'Cookie': SESSION_COOKIE + '=' + (token or self.token)}

    def test_public_and_unclassified_paths(self):
        self.assertEqual(self.client.get('/public').status_code, 200)
        for path in ('/unclassified', '/media/private.txt', '/docs', '/openapi.json', '/missing', '/me/'):
            response = self.client.get(path, headers=self.cookie(), follow_redirects=False)
            self.assertEqual(response.status_code, 404, path)
            self.assertNotIn('canary', response.text)
            self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.calls, [])
        @self.app.get('/added-later')
        def added(): return {'private': True}
        self.assertEqual(self.client.get('/added-later').status_code, 404)

    def test_member_identity_and_no_header_impersonation(self):
        for headers in ({}, {'x-user-id': self.a.id, 'x-user-role': 'operator'}, self.cookie('forged')):
            self.assertEqual(self.client.get('/me', headers=headers).status_code, 401)
        response = self.client.get('/me', headers=self.cookie())
        self.assertEqual(response.json(), {'id': self.a.id})
        self.assertEqual(response.headers['cache-control'], 'no-store')
        second = self.store.issue_session(self.b.id, ttl_seconds=60)
        self.assertEqual(self.client.get('/me', headers=self.cookie(second)).json(), {'id': self.b.id})

    def test_expired_revoked_disabled_and_role_changes(self):
        self.assertEqual(self.client.get('/operator', headers=self.cookie()).status_code, 403)
        self.store.set_role(self.a.id, 'operator')
        self.assertEqual(self.client.get('/operator', headers=self.cookie()).status_code, 200)
        self.store.set_role(self.a.id, 'member')
        self.assertEqual(self.client.get('/operator', headers=self.cookie()).status_code, 403)
        self.store.set_enabled(self.a.id, False)
        self.assertEqual(self.client.get('/me', headers=self.cookie()).status_code, 401)
        self.store.set_enabled(self.a.id, True)
        self.now += 61
        self.assertEqual(self.client.get('/me', headers=self.cookie()).status_code, 401)
        token = self.store.issue_session(self.a.id, ttl_seconds=60)
        self.store.revoke_session(token)
        self.assertEqual(self.client.get('/me', headers=self.cookie(token)).status_code, 401)

    def test_write_requires_origin_and_csrf_before_handler(self):
        valid = {**self.cookie(), 'origin': 'https://beta.example', 'x-csrf-token': session_csrf(self.token)}
        for key in ('origin', 'x-csrf-token'):
            missing = dict(valid); missing.pop(key)
            self.assertEqual(self.client.post('/me', headers=missing).status_code, 403)
            wrong = dict(valid); wrong[key] = 'invalid'
            self.assertEqual(self.client.post('/me', headers=wrong).status_code, 403)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.client.post('/me', headers=valid).status_code, 200)
        self.assertEqual(self.calls, ['write'])

    def test_storage_failure_is_sanitized_and_closed(self):
        with patch.object(self.store, 'resolve_session', side_effect=RuntimeError('secret-canary')):
            response = self.client.get('/me', headers=self.cookie())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret-canary', response.text)
        self.assertEqual(self.calls, [])

    def test_no_http_method_fallback_or_ws_bypass(self):
        self.assertEqual(self.client.head('/public').status_code, 404)
        self.assertEqual(self.client.post('/public').status_code, 404)
        self.assertEqual(self.client.options('/me').status_code, 404)
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/me'): pass

    def test_bad_policy_rejected(self):
        for policies in ({('GET', '/typo'): 'member'}, {('GET', '/me'): 'typo'}, {('POST', '/me'): 'public'}):
            with self.assertRaises(ValueError):
                PublicAccessBoundary(self.app, self.app.router.routes, policies, lambda: self.service)

    def test_modes_and_actual_application_registration(self):
        private = FastAPI()
        configure_access_boundary(private, mode='private')
        self.assertEqual(private.user_middleware, [])
        with self.assertRaises(ValueError): configure_access_boundary(private, mode='publci')
        # Import only: no lifespan/init_db/bot is executed.
        import main
        with patch.dict('os.environ', {'EXPLORER_ACCESS_MODE': 'public'}):
            application = FastAPI()
            application.router.routes = list(main.app.router.routes)
            configure_access_boundary(application)
        with TestClient(application, base_url='https://beta.example') as client:
            self.assertEqual(client.get('/api/health').status_code, 200)
            for path in ('/api/portfolio', '/api/spine/search?q=fixture', '/media/test', '/api/spine/admin/health'):
                self.assertEqual(client.get(path).status_code, 404)
            # Registered auth route is reached but unconfigured, not bypassed.
            self.assertEqual(client.get('/api/auth/session').status_code, 503)


if __name__ == '__main__':
    unittest.main()
