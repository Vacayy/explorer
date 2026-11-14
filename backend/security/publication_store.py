"""Explicitly provisioned publication decisions, separate from source documents."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import time


class PublicationConflict(Exception):
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
                if [r[0] for r in conn.execute('SELECT version FROM publication_metadata')] != [1]:
                    raise ValueError('Unsupported publication schema')
            else:
                conn.execute('CREATE TABLE publication_metadata(version INTEGER NOT NULL)')
                conn.execute('INSERT INTO publication_metadata VALUES(1)')
                conn.execute('''CREATE TABLE publications(
                    doc_id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL,
                    version INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('approved','revoked')),
                    rights_basis TEXT NOT NULL, approved_by TEXT NOT NULL, approved_at REAL NOT NULL,
                    revoked_by TEXT, revoked_at REAL)''')
        os.chmod(self.path, 0o600)

    def get(self, doc_id):
        with self.connection(readonly=True) as conn:
            row = conn.execute('SELECT * FROM publications WHERE doc_id=?', (doc_id,)).fetchone()
        return dict(row) if row else None

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
