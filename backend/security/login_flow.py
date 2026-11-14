"""Google login orchestration. No initialization, network, or logging on import."""
import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import logging
import os
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx

from security.google_identity import verify_google_identity
from security.identity_store import IdentityStore
from security.login_transactions import InvalidLogin, LoginTransactions

CALLBACK_PATH = '/api/auth/google/callback'
SESSION_COOKIE = '__Host-explorer-session'
LOGIN_COOKIE = '__Host-explorer-login'
SESSION_TTL = 86400 * 7


def validate_origin(origin):
    if (not isinstance(origin, str) or not origin
            or any(ord(c) < 33 or ord(c) > 126 for c in origin)
            or '\\' in origin or '%' in origin):
        raise ValueError('Invalid public origin')
    parts = urlsplit(origin)
    if (parts.scheme != 'https' or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.path not in ('', '/') or parts.query
            or parts.fragment or '?' in origin or '#' in origin):
        raise ValueError('Invalid public origin')
    _ = parts.port
    return origin.rstrip('/')


@dataclass(frozen=True)
class AuthConfig:
    client_id: str
    client_secret: str = field(repr=False)
    public_origin: str
    identity_db: Path
    login_db: Path

    def __post_init__(self):
        if not self.client_id.strip() or not self.client_secret.strip():
            raise ValueError('Missing OAuth configuration')
        object.__setattr__(self, 'public_origin', validate_origin(self.public_origin))
        for name in ('identity_db', 'login_db'):
            path = Path(getattr(self, name))
            if not path.is_absolute():
                raise ValueError('Absolute database paths required')
            object.__setattr__(self, name, path)
        if self.identity_db == self.login_db:
            raise ValueError('Separate databases required')

    @classmethod
    def from_environment(cls, env=None):
        env = os.environ if env is None else env
        keys = ('EXPLORER_GOOGLE_CLIENT_ID', 'EXPLORER_GOOGLE_CLIENT_SECRET',
                'EXPLORER_PUBLIC_ORIGIN', 'EXPLORER_IDENTITY_DB', 'EXPLORER_LOGIN_DB')
        if env.get('EXPLORER_AUTH_ENABLED') != '1' or any(not env.get(k) for k in keys):
            raise ValueError('Authentication unavailable')
        return cls(*(env[k] for k in keys))


def exchange_google_code(code, *, config, verifier):
    # Never retain access/refresh tokens or provider exception text.
    try:
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            response = client.post('https://oauth2.googleapis.com/token', data={
                'grant_type': 'authorization_code', 'code': code,
                'client_id': config.client_id, 'client_secret': config.client_secret,
                'redirect_uri': config.public_origin + CALLBACK_PATH, 'code_verifier': verifier})
            response.raise_for_status()
            token = response.json().get('id_token')
            if not isinstance(token, str) or not token:
                raise ValueError('Missing identity token')
            return token
    except Exception:
        raise InvalidLogin('Login could not be completed') from None


def session_csrf(token):
    return hmac.new(token.encode(), b'explorer:session-csrf:v1', hashlib.sha256).hexdigest()


class LoginFlow:
    def __init__(self, config, identities, transactions, *, exchange=exchange_google_code,
                 verify=verify_google_identity):
        self.config = config
        self.identities = identities
        self.transactions = transactions
        self.exchange = exchange
        self.verify = verify

    @classmethod
    def from_environment(cls):
        config = AuthConfig.from_environment()  # All fields validated before I/O.
        identities = IdentityStore(config.identity_db)
        transactions = LoginTransactions(config.login_db)
        transactions.check_ready()
        # No initialization: inspect version via an existing read/write connection.
        with identities._connection() as conn:
            if conn.execute('SELECT version FROM identity_metadata').fetchall()[0][0] != 1:
                raise ValueError('Authentication unavailable')
        return cls(config, identities, transactions)

    def start(self, return_path='/'):
        state, binding, tx = self.transactions.create(return_path)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(tx.verifier.encode()).digest()).decode().rstrip('=')
        query = urlencode(dict(client_id=self.config.client_id, response_type='code',
            redirect_uri=self.config.public_origin + CALLBACK_PATH, scope='openid email profile',
            state=state, nonce=tx.nonce, code_challenge=challenge, code_challenge_method='S256'))
        return 'https://accounts.google.com/o/oauth2/v2/auth?' + query, binding

    def complete(self, code, state, binding, old_token=None):
        try:
            if not isinstance(code, str) or not code or len(code) > 8192:
                raise InvalidLogin('Login could not be completed')
            tx = self.transactions.consume(state, binding)
            token = self.exchange(code, config=self.config, verifier=tx.verifier)
            identity = self.verify(token, client_id=self.config.client_id, expected_nonce=tx.nonce)
            user = self.identities.get_or_create_google_user(identity.issuer, identity.subject)
            new_token = self.identities.issue_session(user.id, ttl_seconds=SESSION_TTL)
            if old_token:
                self.identities.revoke_session(old_token)
            return new_token, tx.return_path
        except Exception:
            raise InvalidLogin('Login could not be completed') from None


class CallbackQueryFilter(logging.Filter):
    """Install on uvicorn.access before serving; strip this callback's query only."""
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if isinstance(args[2], str) and args[2].split('?', 1)[0] in {
                    CALLBACK_PATH, '/api/public/chat', '/api/public/chat/session'}:
                args[2] = args[2].split('?', 1)[0]
                record.args = tuple(args)
        return True
