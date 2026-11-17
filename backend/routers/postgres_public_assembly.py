"""Public mode of the single-path candidate app: login, usage gate and access boundary, on PG.

Called once after every route is registered. In the private (loopback) mode nothing changes. In the public
mode (EXPLORER_ACCESS_MODE=public) it first refuses to start while a schema migration is pending
(pipeline.postgres_schema_migrations), then assembles, with development's environment names:
- the auth routes, their LoginFlow on the PG identity store (pipeline.postgres_identity_store) and a
  separately provisioned login-transaction SQLite (in-progress logins only, as in development);
- the model-call usage gate on the PG chat quota (development's trial policy and identity secret);
- the anonymous trial chat (development's /api/public/chat contract) over the candidate document search;
- the candidate access boundary, outermost, so it runs first; an ambiguous or unclassified route refuses the
  start, and at startup one anonymous public read must pass the whole stack.
"""
import os
from pathlib import Path


def _secret(name, size):
    path = Path(os.environ[name])
    data = path.read_bytes()
    if len(data) != size:
        raise ValueError(f'{name} must hold {size} bytes')
    return data


def install_public(app, factory, *, trial_search=None, trial_read=None):
    from security.access_boundary import configured_access_mode
    if configured_access_mode() != 'public':
        return False
    from pipeline import llm, postgres_usage_gate as gate
    from pipeline.postgres_identity_store import PostgreSQLIdentityStore
    from pipeline.postgres_trial_quota import PostgreSQLTrialQuota
    from routers import auth
    from routers.postgres_access_boundary import CandidateAccessBoundary, check_routes
    from security.login_flow import AuthConfig, LoginFlow
    from security.login_transactions import LoginTransactions
    from security.trial_identity import TrialIdentity
    from security.trial_quota import TrialPolicy

    from pipeline.postgres_schema_migrations import require_applied
    with factory() as conn:
        require_applied(conn)  # never expose before every per-member ledger exists
    config = AuthConfig.from_environment()
    identities = PostgreSQLIdentityStore(factory)
    transactions = LoginTransactions(config.login_db)
    transactions.check_ready()
    service = LoginFlow(config, identities, transactions)
    app.dependency_overrides[auth.get_service] = lambda: service
    app.include_router(auth.router)

    identity = TrialIdentity(_secret('EXPLORER_TRIAL_SECRET_FILE', 32), os.environ['EXPLORER_PUBLIC_ORIGIN'],
                             tuple(v.strip() for v in os.environ.get('EXPLORER_TRIAL_TRUSTED_PROXIES', '').split(',') if v.strip()))
    quota = PostgreSQLTrialQuota(factory, policy=TrialPolicy(
        per_network_day_limit=int(os.environ['EXPLORER_TRIAL_NETWORK_DAY_LIMIT']),
        global_day_limit=int(os.environ['EXPLORER_TRIAL_GLOBAL_DAY_LIMIT']),
        max_in_flight=int(os.environ['EXPLORER_TRIAL_MAX_IN_FLIGHT'])))
    from routers import postgres_member_thesis_fixture
    postgres_member_thesis_fixture.install(app, factory)  # thesis audits: the requester's own
    if trial_search is not None and trial_read is not None:
        from pipeline.postgres_trial_chat import CandidateEvidence, CandidateTrialChat
        from routers import postgres_trial_chat
        app.include_router(postgres_trial_chat.create_router(
            identity, quota, identities, CandidateTrialChat(quota, CandidateEvidence(trial_search, trial_read))))
    gate.install(llm, quota)
    gate.add_middleware(app, identity=identity, factory=factory)
    app.add_middleware(CandidateAccessBoundary, routes=app.router.routes, service_factory=lambda: service)
    check_routes(app.router.routes)  # an ambiguous or unclassified route refuses the start

    @app.on_event('startup')
    async def public_self_check():
        """One anonymous public read through the whole stack (boundary, gate) must answer 200 before serving."""
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://self-check') as client:
            status = (await client.get('/api/spine/feed', params={'size': 1})).status_code
        if status != 200:
            raise RuntimeError(f'Public self-check failed: GET /api/spine/feed answered {status}')
    return True
