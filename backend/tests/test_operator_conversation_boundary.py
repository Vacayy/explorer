"""Operator-only legacy chat and the existing conversation owner boundary."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import database
from routers import spine_ask, spine_conversations
from security.access_boundary import PUBLIC_ROUTE_POLICIES, PublicAccessBoundary
from security.identity_store import IdentityStore
from security.login_flow import SESSION_COOKIE, session_csrf


class OperatorConversationBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.db_patch = patch.object(database, 'DB_PATH', root / 'data.sqlite')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.env_patch = patch.dict('os.environ', {'TELEGRAM_CHAT_ID': 'owner'}, clear=False)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        database.init_db()
        conn = database.get_connection()
        conn.execute("INSERT INTO conversations(id,title,channel,chat_id) VALUES(1,'owner','telegram','owner')")
        conn.execute("INSERT INTO conversations(id,title,channel,chat_id) VALUES(2,'other','telegram','other')")
        conn.execute("INSERT INTO chat_messages(id,conversation_id,role,content) VALUES(10,2,'assistant','other-user-canary')")
        conn.commit()
        conn.close()

        self.identities = IdentityStore(root / 'identity.sqlite')
        self.identities.initialize()
        self.member = self.identities.get_or_create_google_user('accounts.google.com', 'member')
        self.operator = self.identities.get_or_create_google_user('accounts.google.com', 'operator')
        self.identities.set_role(self.operator.id, 'operator')
        self.member_token = self.identities.issue_session(self.member.id, ttl_seconds=300)
        self.operator_token = self.identities.issue_session(self.operator.id, ttl_seconds=300)
        app = FastAPI()
        app.include_router(spine_conversations.router)
        app.include_router(spine_ask.router)
        policies = {k: v for k, v in PUBLIC_ROUTE_POLICIES.items()
                    if k[1].startswith('/api/spine/conversations') or k[1] == '/api/spine/ask'}
        service = SimpleNamespace(identities=self.identities, config=SimpleNamespace(public_origin='https://example.test'))
        app.add_middleware(PublicAccessBoundary, routes=app.router.routes,
                           policies=policies, service_factory=lambda: service)
        self.client = TestClient(app, base_url='https://example.test')
        self.addCleanup(self.client.close)

    def headers(self, token, csrf=True):
        headers = {'cookie': SESSION_COOKIE + '=' + token, 'origin': 'https://example.test'}
        if csrf:
            headers['x-csrf-token'] = session_csrf(token)
        return headers

    def test_only_operator_can_access_and_writes_require_csrf(self):
        path = '/api/spine/conversations'
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(path, headers=self.headers(self.member_token)).status_code, 403)
        response = self.client.get(path, headers=self.headers(self.operator_token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.json()], [1])
        self.assertEqual(self.client.get(path + '/1', headers=self.headers(self.operator_token)).status_code, 200)
        self.assertEqual(self.client.patch(path + '/1', json={'title': 'changed'},
                                           headers=self.headers(self.operator_token, csrf=False)).status_code, 403)
        self.assertEqual(self.client.patch(path + '/1', json={'title': 'changed'},
                                           headers=self.headers(self.operator_token)).status_code, 200)
        self.assertEqual(self.client.post('/api/spine/ask', json={'question': 'test'},
                                         headers=self.headers(self.operator_token, csrf=False)).status_code, 403)
        with patch.object(spine_ask, '_generate_answer') as generate:
            response = self.client.post('/api/spine/ask', json={'question': 'test'},
                                        headers=self.headers(self.operator_token))
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(response.json()['conversation_id'])
            generate.assert_called_once()

    def test_operator_cannot_read_or_modify_other_persons_thread(self):
        headers = self.headers(self.operator_token)
        for path in ('/api/spine/conversations/2', '/api/spine/conversations/2/stream'):
            response = self.client.get(path, headers=headers)
            self.assertEqual(response.status_code, 404)
            self.assertNotIn('other-user-canary', response.text)
        response = self.client.patch('/api/spine/conversations/2', json={'title': 'changed'}, headers=headers)
        self.assertEqual(response.status_code, 404)
        for body in ({'question': 'test', 'conversation_id': 2},
                     {'question': 'test', 'quote': {'message_id': 10, 'selected': 'test'}}):
            self.assertEqual(self.client.post('/api/spine/ask', json=body, headers=headers).status_code, 404)
        conn = database.get_connection()
        try:
            self.assertEqual(conn.execute('SELECT title FROM conversations WHERE id=2').fetchone()[0], 'other')
            self.assertEqual(conn.execute('SELECT count(*) FROM chat_messages').fetchone()[0], 1)
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()
