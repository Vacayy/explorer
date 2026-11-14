import logging
import json
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from routers.trial_chat import router, trial_service
from security.access_boundary import PublicAccessBoundary
from security.login_flow import CallbackQueryFilter
from security.trial_chat import TrialChat
from security.trial_identity import COOKIE_NAME, TrialIdentity
from security.trial_quota import TrialPolicy, TrialQuota
from security.trial_service import TrialService


class Evidence:
    def gather(self, query, document_ids):
        self.last = (query, document_ids)
        return self
    def model_input(self):
        return 'approved fixture'
    def finalize(self, context, answer, citation_ids):
        return {'answer': answer, 'citations': [{'id': 'D1', 'title': 'Approved', 'url': '/doc/1'}], 'partial': False}


class TrialHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.quota = TrialQuota(Path(self.tmp.name) / 'quota', policy=TrialPolicy(
            per_network_day_limit=10, global_day_limit=10, max_in_flight=1))
        self.quota.initialize()
        self.identity = TrialIdentity(b'a' * 32, 'https://beta.example')
        self.evidence = Evidence()
        self.calls = []
        self.service = TrialService(self.identity, self.quota, TrialChat(self.quota, self.evidence, self))
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[trial_service] = lambda: self.service
        self.app.add_middleware(PublicAccessBoundary, routes=self.app.router.routes, policies={
            ('GET', '/api/public/chat/session'): 'trial', ('POST', '/api/public/chat'): 'trial'})
        self.client = TestClient(self.app, base_url='https://beta.example', client=('192.0.2.1', 4000))
        self.addCleanup(self.client.close)
        self.headers = {'Origin': 'https://beta.example'}

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        self.quota.mark_started(kwargs['reservation_id'])
        self.quota.finish(kwargs['reservation_id'])
        return {'answer': 'fixture answer', 'citation_ids': ['D1']}

    def session(self):
        response = self.client.get('/api/public/chat/session', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.headers['X-CSRF-Token'] = response.json()['csrf_token']
        return response

    def ask(self, **kwargs):
        return self.client.post('/api/public/chat', headers=self.headers,
                                json=kwargs or {'question': 'question canary', 'document_ids': [1]})

    def test_cookie_csrf_success_and_server_quota(self):
        session = self.session()
        cookie = session.headers['set-cookie']
        for attribute in ('Secure', 'HttpOnly', 'SameSite=lax', 'Path=/'):
            self.assertIn(attribute, cookie)
        self.assertNotIn('Domain=', cookie)
        for remaining in (2, 1, 0):
            response = self.ask()
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['remaining'], remaining)
            self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.ask().status_code, 429)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.session().json()['remaining'], 0)

    def test_untrusted_forwarding_cannot_reset_network_limit(self):
        self.quota.policy = TrialPolicy(per_network_day_limit=1, global_day_limit=10, max_in_flight=1)
        self.session()
        self.assertEqual(self.ask().status_code, 200)
        self.client.cookies.clear()
        self.session()
        self.headers['X-Explorer-Client-IP'] = '198.51.100.1'
        self.assertEqual(self.ask().status_code, 429)

    def test_missing_identity_csrf_wrong_origin_rejected_before_execution(self):
        self.assertEqual(self.ask().status_code, 403)
        self.session()
        for headers in ({}, {'Origin': 'https://evil.example'},
                        {'Origin': 'https://beta.example', 'X-CSRF-Token': 'wrong'},
                        {**self.headers, 'Sec-Fetch-Site': 'cross-site'}):
            response = self.client.post('/api/public/chat', headers=headers, json={'question': 'canary'})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.calls, [])

    def test_invalid_and_large_body_never_echo_input_or_execute(self):
        self.session()
        for body in ({'question': 'canary', 'unexpected': 'private-canary'},
                     {'question': 'canary', 'document_ids': [True]},
                     {'question': 'canary', 'document_ids': [1, 1]},
                     {'question': 'canary', 'history': [{'role': 'system', 'content': 'private-canary'}]},
                     {'question': '😀' * 4000}, {'question': '\ud800'}):
            response = self.client.post('/api/public/chat', headers={**self.headers, 'Content-Type': 'application/json'},
                                        content=json.dumps(body).encode())
            self.assertEqual(response.status_code, 422, response.text)
            self.assertNotIn('canary', response.text)
        response = self.client.post('/api/public/chat', headers=self.headers,
                                    content=b'private-canary' * 10000)
        self.assertEqual(response.status_code, 413)
        self.assertNotIn('canary', response.text)
        self.assertEqual(self.calls, [])

    def test_explicit_document_search_contract_and_history(self):
        self.session()
        response = self.ask(question='How did revenue change?', search_query='revenue', document_ids=[1],
                            history=[{'role': 'user', 'content': 'previous'}])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.evidence.last, ('revenue', [1]))
        self.assertEqual(self.calls[0]['history'], [{'role': 'user', 'content': 'previous'}])

    def test_unconfigured_service_fails_closed_and_private_mode_unavailable(self):
        self.app.dependency_overrides.clear()
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(self.client.get('/api/public/chat/session').status_code, 503)
        private = FastAPI()
        private.include_router(router)
        with TestClient(private) as client:
            self.assertEqual(client.get('/api/public/chat/session').status_code, 404)

    def test_query_log_filter_drops_chat_query(self):
        for path in ('/api/public/chat', '/api/public/chat/session'):
            record = logging.LogRecord('uvicorn.access', 20, '', 0, '%s %s %s %s %s',
                                       ('client', 'POST', path + '?question=private-canary', '1.1', 200), None)
            CallbackQueryFilter().filter(record)
            self.assertNotIn('private-canary', record.getMessage())

    def test_stream_limit_stops_receiving_before_json_parser(self):
        reads = []
        async def receive():
            reads.append(1)
            return {'type': 'http.request', 'body': b'x' * 50000, 'more_body': True}
        request = Request({'type': 'http', 'method': 'POST', 'path': '/api/public/chat',
                           'headers': [], 'query_string': b''}, receive)
        route = next(r for r in router.routes if r.path == '/api/public/chat')
        response = asyncio.run(route.get_route_handler()(request))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(len(reads), 2)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
