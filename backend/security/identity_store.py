"""Identity/session persistence, NOT an OIDC verifier.

The caller must validate Google's signature, issuer, audience, expiry, nonce and
login flow before calling get_or_create_google_user. Email is never an identity
key. Administrative methods require authorization by their caller; this module
does not expose HTTP endpoints. No application/database configuration is read.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Callable
import uuid


@dataclass(frozen=True)
class User:
    id: str
    role: str
    enabled: bool


class IdentityStore:
    """A separately provisioned SQLite store. Call initialize() explicitly.

    Only token hashes are persisted. Treat issued tokens as credentials: callers
    must not log them. Roles and enabled state are read afresh on every resolve.
    """

    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time):
        self.path = Path(path).absolute()
        self._clock = clock

    @contextmanager
    def _connection(self):
        # mode=rw prevents ordinary operations from creating a missing database.
        uri = self.path.as_uri() + "?mode=rw"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        """Explicitly create schema; refuse an unrelated, nonempty database."""
        # Create exclusively with private permissions before SQLite opens it.
        # Existing files must pass schema validation before permissions change.
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with self._connection() as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )}
            expected = {"identity_metadata", "users", "google_identities", "sessions"}
            if tables:
                if tables != expected:
                    raise ValueError("Not an identity database")
                version = conn.execute("SELECT version FROM identity_metadata").fetchall()
                if len(version) != 1 or version[0][0] != 1:
                    raise ValueError("Unsupported identity schema")
                os.chmod(self.path, 0o600)
                return
            conn.execute("CREATE TABLE identity_metadata (version INTEGER NOT NULL)")
            conn.execute("INSERT INTO identity_metadata VALUES (1)")
            conn.execute("""CREATE TABLE users (
                id TEXT PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('member','operator')),
                enabled INTEGER NOT NULL CHECK(enabled IN (0,1)))""")
            conn.execute("""CREATE TABLE google_identities (
                issuer TEXT NOT NULL, subject TEXT NOT NULL,
                user_id TEXT NOT NULL REFERENCES users(id), PRIMARY KEY(issuer,subject))""")
            conn.execute("""CREATE TABLE sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                expires_at REAL NOT NULL)""")
            conn.execute("CREATE INDEX sessions_user ON sessions(user_id)")
            conn.execute("CREATE INDEX sessions_expiry ON sessions(expires_at)")
            os.chmod(self.path, 0o600)

    @staticmethod
    def _user(row) -> User:
        return User(row["id"], row["role"], bool(row["enabled"]))

    def get_or_create_google_user(self, issuer: str, subject: str) -> User:
        """Accept ONLY already-verified claims; this does not verify a token."""
        if issuer not in ("https://accounts.google.com", "accounts.google.com"):
            raise ValueError("Unsupported Google issuer")
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 255:
            raise ValueError("Invalid Google subject")
        issuer = "https://accounts.google.com"
        with self._connection() as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("""SELECT u.* FROM users u JOIN google_identities g
                ON u.id=g.user_id WHERE g.issuer=? AND g.subject=?""", (issuer, subject)).fetchone()
            if row:
                return self._user(row)
            user_id = uuid.uuid4().hex
            conn.execute("INSERT INTO users VALUES (?, 'member', 1)", (user_id,))
            conn.execute("INSERT INTO google_identities VALUES (?,?,?)", (issuer, subject, user_id))
            return User(user_id, "member", True)

    def set_role(self, user_id: str, role: str) -> None:
        """Explicit administrative action; caller must authorize it."""
        if role not in ("member", "operator"):
            raise ValueError("Invalid role")
        with self._connection() as conn, conn:
            if conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id)).rowcount != 1:
                raise LookupError("Unknown user")

    def set_enabled(self, user_id: str, enabled: bool) -> None:
        """Disabling also revokes sessions so re-enabling cannot revive them."""
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        with self._connection() as conn, conn:
            if conn.execute("UPDATE users SET enabled=? WHERE id=?", (int(enabled), user_id)).rowcount != 1:
                raise LookupError("Unknown user")
            if not enabled:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def issue_session(self, user_id: str, *, ttl_seconds: int) -> str:
        if type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise ValueError("Session lifetime must be positive integer seconds")
        expires = self._clock() + ttl_seconds
        if not math.isfinite(expires):
            raise ValueError("Invalid session expiry")
        token = secrets.token_urlsafe(32)
        with self._connection() as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT enabled FROM users WHERE id=?", (user_id,)).fetchone()
            if not row or not row[0]:
                raise PermissionError("User cannot create a session")
            conn.execute("INSERT INTO sessions VALUES (?,?,?)", (self._digest(token), user_id, expires))
        return token

    def resolve_session(self, token: str) -> User | None:
        if not isinstance(token, str) or not token or len(token) > 256:
            return None
        with self._connection() as conn:
            row = conn.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1""",
                (self._digest(token), self._clock())).fetchone()
            return self._user(row) if row else None

    def revoke_session(self, token: str) -> None:
        if not isinstance(token, str) or not token or len(token) > 256:
            return
        with self._connection() as conn, conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (self._digest(token),))

    def expire_sessions(self) -> int:
        """Optional housekeeping; expiry is enforced even without this call."""
        with self._connection() as conn, conn:
            return conn.execute("DELETE FROM sessions WHERE expires_at<=?", (self._clock(),)).rowcount
