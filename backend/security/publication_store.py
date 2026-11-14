"""Explicitly provisioned publication decisions, separate from source documents."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import time
import json
from cryptography.fernet import Fernet, InvalidToken


class PublicationConflict(Exception):
    pass


class InvalidCursor(Exception):
    pass


class PublicationStore:
    def __init__(self, path: Path):
        self.path = Path(path).absolute()

    @contextmanager
    def connection(self, *, readonly=False):
        conn = sqlite3.connect(self.path.as_uri() + ('?mode=ro' if readonly else '?mode=rw'), uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self):
        """Explicit local provisioning only; never called by a request/import."""
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
                if tables != {'publication_metadata', 'publications'}:
                    raise ValueError('Not a publication store')
                versions = [r[0] for r in conn.execute('SELECT version FROM publication_metadata')]
                if versions == [1]:
                    conn.execute('ALTER TABLE publication_metadata ADD COLUMN cursor_key TEXT')
                    conn.execute('UPDATE publication_metadata SET version=2,cursor_key=?', (Fernet.generate_key().decode(),))
                elif versions != [2]:
                    raise ValueError('Unsupported publication schema')
            else:
                conn.execute('CREATE TABLE publication_metadata(version INTEGER NOT NULL,cursor_key TEXT NOT NULL)')
                conn.execute('INSERT INTO publication_metadata VALUES(2,?)', (Fernet.generate_key().decode(),))
                conn.execute('''CREATE TABLE publications(
                    doc_id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL,
                    version INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('approved','revoked')),
                    rights_basis TEXT NOT NULL, approved_by TEXT NOT NULL, approved_at REAL NOT NULL,
                    revoked_by TEXT, revoked_at REAL)''')
        os.chmod(self.path, 0o600)

    def cursor_cipher(self):
        with self.connection(readonly=True) as conn:
            row = conn.execute('SELECT cursor_key FROM publication_metadata WHERE version=2').fetchone()
        if row is None:
            raise ValueError('Publication cursor schema not prepared')
        return Fernet(row[0])

    def encode_cursor(self, before, query):
        # Fixed padded plaintext hides the size of the internal source ID.
        payload = json.dumps({'v':1,'before':before,'q':query},ensure_ascii=False).encode()
        return self.cursor_cipher().encrypt(payload.ljust(1024,b' ')).decode()

    def decode_cursor(self, token, query):
        cipher = self.cursor_cipher()
        try:
            payload = json.loads(cipher.decrypt(token,ttl=3600))
            before = payload['before']
            if payload.get('v') != 1 or payload.get('q') != query or type(before) is not int or not 1 <= before <= 2**63-1:
                raise InvalidCursor()
            return before
        except (InvalidToken, ValueError, TypeError, KeyError):
            raise InvalidCursor() from None

    def get(self, doc_id):
        with self.connection(readonly=True) as conn:
            row = conn.execute('SELECT * FROM publications WHERE doc_id=?', (doc_id,)).fetchone()
        return dict(row) if row else None

    def candidates(self, before, limit):
        with self.connection(readonly=True) as conn:
            return [row[0] for row in conn.execute('''SELECT doc_id FROM publications
                WHERE status='approved' AND (? IS NULL OR doc_id<?)
                ORDER BY doc_id DESC LIMIT ?''', (before, before, limit))]

    def all_approved(self, fingerprints):
        """One SQLite read snapshot for the final bounded evidence set."""
        if not 1 <= len(fingerprints) <= 4:
            return False
        placeholders = ','.join('?' for _ in fingerprints)
        with self.connection(readonly=True) as conn:
            rows = conn.execute(f'SELECT doc_id,status,fingerprint FROM publications WHERE doc_id IN ({placeholders})',
                                tuple(fingerprints)).fetchall()
        return len(rows) == len(fingerprints) and all(
            row['status'] == 'approved' and row['fingerprint'] == fingerprints[row['doc_id']] for row in rows)

    def approve(self, doc_id, fingerprint, expected_version, actor, basis):
        if not actor or not basis.strip():
            raise ValueError('Approval evidence required')
        with self.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT version FROM publications WHERE doc_id=?', (doc_id,)).fetchone()
            version = row[0] if row else 0
            if expected_version != version:
                raise PublicationConflict()
            version += 1
            conn.execute('''INSERT INTO publications VALUES(?,?,?,'approved',?,?,?,NULL,NULL)
                ON CONFLICT(doc_id) DO UPDATE SET fingerprint=excluded.fingerprint,version=excluded.version,
                status='approved',rights_basis=excluded.rights_basis,approved_by=excluded.approved_by,
                approved_at=excluded.approved_at,revoked_by=NULL,revoked_at=NULL''',
                (doc_id, fingerprint, version, basis.strip(), actor, time.time()))
        return {'id': doc_id, 'version': version, 'status': 'approved'}

    def revoke(self, doc_id, expected_version, actor):
        with self.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT version FROM publications WHERE doc_id=?', (doc_id,)).fetchone()
            if row is None or row[0] != expected_version:
                raise PublicationConflict()
            version = row[0] + 1
            conn.execute("UPDATE publications SET status='revoked',version=?,revoked_by=?,revoked_at=? WHERE doc_id=?",
                         (version, actor, time.time(), doc_id))
        return {'id': doc_id, 'version': version, 'status': 'revoked'}
