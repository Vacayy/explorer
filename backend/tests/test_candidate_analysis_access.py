import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.postgres_access_boundary import CandidateAccessBoundary, route_policy
from security.identity_store import IdentityStore
from security.login_flow import SESSION_COOKIE


class CandidateAnalysisAccessTest(unittest.TestCase):
    def test_private_runs_and_discovery_are_operator_only(self):
        paths = ['/api/analysis/runs', '/api/analysis/runs/{run_id}',
                 '/api/analysis/runs/{run_id}/events', '/api/analysis/runs/{run_id}/artifacts/{artifact_id}',
                 '/api/analysis/discovery/strategies', '/api/analysis/discovery/cases/{case_id}']
        for path in paths:
            self.assertEqual(route_policy('GET', path), 'operator')
            self.assertEqual(route_policy('POST', path), 'operator')
        self.assertEqual(route_policy('GET', '/api/analysis/strategies'), 'public')

        with tempfile.TemporaryDirectory() as directory:
            identities = IdentityStore(Path(directory) / 'identity.sqlite', clock=lambda: 1000)
            identities.initialize()
            operator = identities.get_or_create_google_user('accounts.google.com', 'operator')
            member = identities.get_or_create_google_user('accounts.google.com', 'member')
            identities.set_role(operator.id, 'operator')
            op_token = identities.issue_session(operator.id, ttl_seconds=60)
            member_token = identities.issue_session(member.id, ttl_seconds=60)
            service = SimpleNamespace(identities=identities, config=SimpleNamespace(public_origin='https://beta.example'))
            app = FastAPI()
            @app.get('/api/analysis/runs')
            def runs():
                return {'items': []}
            app.add_middleware(CandidateAccessBoundary, routes=app.router.routes, service_factory=lambda: service)
            with TestClient(app, base_url='https://beta.example') as client:
                self.assertEqual(client.get('/api/analysis/runs').status_code, 401)
                self.assertEqual(client.get('/api/analysis/runs', headers={'Cookie': SESSION_COOKIE + '=' + member_token}).status_code, 403)
                self.assertEqual(client.get('/api/analysis/runs', headers={'Cookie': SESSION_COOKIE + '=' + op_token}).status_code, 200)
