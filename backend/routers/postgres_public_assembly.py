"""Public mode of the single-path candidate app: login, usage gate and access boundary, on PG.

Called once after every route is registered. In the private (loopback) mode nothing changes. In the public
mode (EXPLORER_ACCESS_MODE=public) it assembles, with development's environment names:
- the auth routes, their LoginFlow on the PG identity store (pipeline.postgres_identity_store) and a
  separately provisioned login-transaction SQLite (in-progress logins only, as in development);
- the model-call usage gate on the PG chat quota (development's trial policy and identity secret);
- the candidate access boundary, outermost, so it runs first.
"""
import os
from pathlib import Path


def _secret(name, size):
    path = Path(os.environ[name])
    data = path.read_bytes()
    if len(data) != size:
        raise ValueError(f'{name} must hold {size} bytes')
    return data


def install_public(app, factory):
    from security.access_boundary import configured_access_mode
    if configured_access_mode() != 'public':
        return False
    from pipeline import llm, postgres_usage_gate as gate
    from pipeline.postgres_identity_store import PostgreSQLIdentityStore
    from pipeline.postgres_trial_quota import PostgreSQLTrialQuota
    from routers import auth
    from routers.postgres_access_boundary import CandidateAccessBoundary
    from security.login_flow import AuthConfig, LoginFlow
    from security.login_transactions import LoginTransactions
    from security.trial_identity import TrialIdentity
    from security.trial_quota import TrialPolicy

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
    gate.install(llm, quota)
    gate.add_middleware(app, identity=identity, factory=factory)
    app.add_middleware(CandidateAccessBoundary, routes=app.router.routes, service_factory=lambda: service)
    return True
