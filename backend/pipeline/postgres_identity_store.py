"""IdentityStore on the single-path candidate's PG (development security.identity_store, same interface).

Users are `principals` (the same id as development's users.id, so migrated members keep their ids and the
personal ledgers key on them), with their Google identities and sessions. As in development: an OIDC
verifier must have validated the token before get_or_create_google_user; email is never an identity key;
only token hashes are kept; role and enabled state are read afresh on every resolve; disabling revokes
sessions. SQLite's BEGIN IMMEDIATE becomes a transaction-scoped advisory lock / row lock.
"""
import math
import secrets
import time
import uuid
from typing import Callable

from pipeline.postgres_graph_fixture import _guard
from security.identity_store import IdentityStore, User

LOCK = 'identity-store'


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('principals')").fetchone()[0] is not None:
            raise ValueError('Identity store already initialized')
        conn.execute("CREATE TABLE principals (id TEXT PRIMARY KEY,role TEXT NOT NULL CHECK(role IN ('member','operator')),"
                     'enabled BOOLEAN NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now())')
        conn.execute('CREATE TABLE google_identities (issuer TEXT NOT NULL,subject TEXT NOT NULL,'
                     'principal_id TEXT NOT NULL REFERENCES principals(id),PRIMARY KEY(issuer,subject))')
        conn.execute('CREATE TABLE sessions (token_hash TEXT PRIMARY KEY,principal_id TEXT NOT NULL REFERENCES principals(id),'
                     'expires_at DOUBLE PRECISION NOT NULL)')
        conn.execute('CREATE INDEX sessions_principal ON sessions(principal_id)')
        conn.execute('CREATE INDEX sessions_expiry ON sessions(expires_at)')


class PostgreSQLIdentityStore:
    def __init__(self, connect, *, clock: Callable[[], float] = time.time):
        self.connect = connect
        self._clock = clock

    _digest = staticmethod(IdentityStore._digest)

    @staticmethod
    def _user(row) -> User:
        return User(row[0], row[1], bool(row[2]))

    def get_or_create_google_user(self, issuer: str, subject: str) -> User:
        """Accept ONLY already-verified claims; this does not verify a token."""
        if issuer not in ('https://accounts.google.com', 'accounts.google.com'):
            raise ValueError('Unsupported Google issuer')
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 255:
            raise ValueError('Invalid Google subject')
        issuer = 'https://accounts.google.com'
        with self.connect() as conn, conn.transaction():
            _guard(conn)
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (LOCK,))
            row = conn.execute('SELECT p.id,p.role,p.enabled FROM principals p JOIN google_identities g ON p.id=g.principal_id '
                               'WHERE g.issuer=%s AND g.subject=%s', (issuer, subject)).fetchone()
            if row:
                return self._user(row)
            user_id = uuid.uuid4().hex
            conn.execute("INSERT INTO principals(id,role,enabled) VALUES (%s,'member',true)", (user_id,))
            conn.execute('INSERT INTO google_identities VALUES (%s,%s,%s)', (issuer, subject, user_id))
            return User(user_id, 'member', True)

    def set_role(self, user_id: str, role: str) -> None:
        """Explicit administrative action; caller must authorize it."""
        if role not in ('member', 'operator'):
            raise ValueError('Invalid role')
        with self.connect() as conn, conn.transaction():
            _guard(conn)
            if conn.execute('UPDATE principals SET role=%s WHERE id=%s', (role, user_id)).rowcount != 1:
                raise LookupError('Unknown user')

    def set_enabled(self, user_id: str, enabled: bool) -> None:
        """Disabling also revokes sessions so re-enabling cannot revive them."""
        if not isinstance(enabled, bool):
            raise ValueError('enabled must be boolean')
        with self.connect() as conn, conn.transaction():
            _guard(conn)
            if conn.execute('UPDATE principals SET enabled=%s WHERE id=%s', (enabled, user_id)).rowcount != 1:
                raise LookupError('Unknown user')
            if not enabled:
                conn.execute('DELETE FROM sessions WHERE principal_id=%s', (user_id,))

    def issue_session(self, user_id: str, *, ttl_seconds: int) -> str:
        if type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise ValueError('Session lifetime must be positive integer seconds')
        expires = self._clock() + ttl_seconds
        if not math.isfinite(expires):
            raise ValueError('Invalid session expiry')
        token = secrets.token_urlsafe(32)
        with self.connect() as conn, conn.transaction():
            _guard(conn)
            row = conn.execute('SELECT enabled FROM principals WHERE id=%s FOR UPDATE', (user_id,)).fetchone()
            if not row or not row[0]:
                raise PermissionError('User cannot create a session')
            conn.execute('INSERT INTO sessions VALUES (%s,%s,%s)', (self._digest(token), user_id, expires))
        return token

    def resolve_session(self, token: str) -> User | None:
        if not isinstance(token, str) or not token or len(token) > 256:
            return None
        with self.connect() as conn:
            _guard(conn)
            row = conn.execute('SELECT p.id,p.role,p.enabled FROM sessions s JOIN principals p ON p.id=s.principal_id '
                               'WHERE s.token_hash=%s AND s.expires_at>%s AND p.enabled',
                               (self._digest(token), self._clock())).fetchone()
            return self._user(row) if row else None

    def revoke_session(self, token: str) -> None:
        if not isinstance(token, str) or not token or len(token) > 256:
            return
        with self.connect() as conn:
            _guard(conn)
            conn.execute('DELETE FROM sessions WHERE token_hash=%s', (self._digest(token),))

    def expire_sessions(self) -> int:
        """Optional housekeeping; expiry is enforced even without this call."""
        with self.connect() as conn:
            _guard(conn)
            return conn.execute('DELETE FROM sessions WHERE expires_at<=%s', (self._clock(),)).rowcount
