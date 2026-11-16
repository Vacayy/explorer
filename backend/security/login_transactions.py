"""Short-lived, browser-bound, single-use OAuth transactions; explicit storage."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import unquote, urlsplit


def safe_return_path(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('Invalid return path')
    decoded = value
    for _ in range(4):
        if (not decoded.startswith('/') or decoded.startswith('//') or '\\' in decoded
                or any(ord(c) < 32 or ord(c) == 127 for c in decoded)):
            raise ValueError('Invalid return path')
        parsed = urlsplit(decoded)
        if parsed.scheme or parsed.netloc:
            raise ValueError('Invalid return path')
        next_value = unquote(decoded)
        if next_value == decoded:
            return value
        decoded = next_value
    raise ValueError('Invalid return path')


class InvalidLogin(ValueError):
    pass


@dataclass(frozen=True)
class LoginTransaction:
    nonce: str = field(repr=False)
    verifier: str = field(repr=False)
    return_path: str = field(repr=False)


class LoginTransactions:
    def __init__(self, path: Path, *, clock=time.time):
        self.path = Path(path).absolute()
        self.clock = clock

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=10)
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self):
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with self.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables:
                if tables != {'login_metadata', 'login_transactions'}:
                    raise ValueError('Not a login transaction database')
                if conn.execute('SELECT version FROM login_metadata').fetchall() != [(1,)]:
                    raise ValueError('Unsupported login schema')
            else:
                conn.execute('CREATE TABLE login_metadata (version INTEGER NOT NULL)')
                conn.execute('INSERT INTO login_metadata VALUES (1)')
                conn.execute('''CREATE TABLE login_transactions (
                    state_hash TEXT PRIMARY KEY, binding_hash TEXT NOT NULL,
                    nonce TEXT NOT NULL, verifier TEXT NOT NULL,
                    return_path TEXT NOT NULL, expires_at REAL NOT NULL)''')
            os.chmod(self.path, 0o600)

    def check_ready(self):
        with self.connection() as conn:
            if conn.execute('SELECT version FROM login_metadata').fetchall() != [(1,)]:
                raise ValueError('Unsupported login schema')

    @staticmethod
    def _hash(value):
        if not isinstance(value, str) or re.fullmatch('[A-Za-z0-9_-]{43}', value) is None:
            raise InvalidLogin('Login could not be completed')
        return hashlib.sha256(value.encode()).hexdigest()

    def create(self, return_path='/'):
        return_path = safe_return_path(return_path)
        state, binding, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
        transaction = LoginTransaction(nonce, verifier, return_path)
        with self.connection() as conn, conn:
            conn.execute('DELETE FROM login_transactions WHERE expires_at<=?', (self.clock(),))
            conn.execute('INSERT INTO login_transactions VALUES (?,?,?,?,?,?)',
                         (self._hash(state), self._hash(binding), nonce, verifier, return_path, self.clock() + 300))
        return state, binding, transaction

    def consume(self, state, binding):
        state_hash, binding_hash = self._hash(state), self._hash(binding)
        with self.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('''SELECT nonce,verifier,return_path FROM login_transactions
                WHERE state_hash=? AND binding_hash=? AND expires_at>?''',
                (state_hash, binding_hash, self.clock())).fetchone()
            if row is None:
                raise InvalidLogin('Login could not be completed')
            conn.execute('DELETE FROM login_transactions WHERE state_hash=?', (state_hash,))
            return LoginTransaction(*row)
