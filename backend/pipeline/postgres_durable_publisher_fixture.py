"""Recoverable lexical publisher for explicitly disposable PG fixtures.

This prototype retains old and interrupted schemas. It is not a public API,
a cross-process reader lease, a scheduler, or an operational cleanup policy.
"""
from contextlib import contextmanager
from pathlib import Path
import re
import threading
import uuid

import psycopg
from psycopg import sql
from pipeline.postgres_document_read import PostgreSQLDocumentReader
from pipeline.postgres_graph_fixture import _guard
from pipeline.postgres_note_overlay_fixture import copy_with_note_changes
from pipeline.postgres_search_feed import search_feed
from pipeline.postgres_search_snapshot import SearchSnapshot

_LOCK = 0x4558504C5055424C
_SCHEMA = re.compile(r'^refactor_fixture_[0-9a-f]{32}$')


class DurableFixturePublisher:
    def __init__(self, factory, source_schema, target_factory):
        if not _SCHEMA.fullmatch(source_schema or ''):
            raise ValueError('Disposable source schema required')
        self.factory=factory
        self.source_schema=source_schema
        self.target_factory=target_factory
        self.lock=threading.RLock()
        self.active=None
        self.cleanup_errors=[]

    @contextmanager
    def _lease(self):
        with self.factory() as conn:
            _guard(conn)
            if conn.execute('SELECT current_schema()').fetchone()[0] != self.source_schema:
                raise ValueError('Source schema mismatch')
            if not conn.execute('SELECT pg_try_advisory_lock(%s)',(_LOCK,)).fetchone()[0]:
                raise RuntimeError('Another fixture publisher is active')
            try:
                yield conn
            finally:
                try:
                    conn.execute('SELECT pg_advisory_unlock(%s)',(_LOCK,))
                except psycopg.Error:
                    # A lost connection has already released the session lock.
                    pass

    def initialize(self):
        with self._lease() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS fixture_publication_state (
                singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
                active_schema TEXT NOT NULL, generation UUID NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS fixture_publication_stages (
                schema_name TEXT PRIMARY KEY, state TEXT NOT NULL
                CHECK (state IN ('building','active','retained')), generation UUID UNIQUE)''')

    def restore(self):
        """Restore the last committed pointer; old data stays readable on failure."""
        with self.lock, self._lease() as source:
            row=source.execute('SELECT active_schema,generation FROM fixture_publication_state WHERE singleton').fetchone()
            if row is None:
                return False
            schema,generation=row
            if not _SCHEMA.fullmatch(schema or '') or schema==self.source_schema:
                raise ValueError('Invalid active fixture schema')
            with self.target_factory(schema) as target:
                target.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                if target.execute('SELECT current_schema()').fetchone()[0] != schema:
                    raise ValueError('Target schema mismatch')
                actual=target.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
                if actual is None or actual[0]!=generation:
                    raise ValueError('Active generation mismatch')
                replacement=SearchSnapshot.from_postgres(target,lexical_only=True)
            old,self.active=self.active,(schema,replacement)
            if old is not None:
                try:
                    old[1].close()
                except Exception as exc:
                    self.cleanup_errors.append(type(exc).__name__)
            return True

    def publish(self):
        """Build before atomically switching the durable pointer; retain old data."""
        with self.lock, self._lease() as source:
            schema='refactor_fixture_'+uuid.uuid4().hex
            source.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            source.execute("INSERT INTO fixture_publication_stages(schema_name,state) VALUES (%s,'building')",(schema,))
            # Commit the cleanup record before the potentially long build.
            source.commit()
            with self.target_factory(schema) as target:
                _guard(target)
                if target.execute('SELECT current_schema()').fetchone()[0] != schema:
                    raise ValueError('Target schema mismatch')
                target.execute((Path(__file__).resolve().parents[1]/'refactor_sql/document_projection.sql').read_text())
            replacement=None
            try:
                with self.factory() as c:
                    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                    result=copy_with_note_changes(c,self.source_schema,schema)
                    rows=c.execute("SELECT (row_data->>'id')::bigint,row_data->>'title',row_data->>'markdown' "
                                   "FROM legacy_snapshot_rows WHERE table_name='raw_documents' ORDER BY row_ordinal").fetchall()
                    replacement=SearchSnapshot(result['generation'],rows)
                try:
                    # The pointer must commit on the session holding the lease.
                    # Losing that session therefore cannot activate a candidate.
                    with source.transaction():
                        _guard(source)
                        actual=source.execute(sql.SQL('SELECT generation_id FROM {}.snapshot_metadata WHERE singleton').format(sql.Identifier(schema))).fetchone()
                        if actual is None or actual[0]!=result['generation']:
                            raise ValueError('Candidate generation mismatch')
                        source.execute("UPDATE fixture_publication_stages SET state='retained' WHERE state='active'")
                        changed=source.execute("UPDATE fixture_publication_stages SET state='active',generation=%s WHERE schema_name=%s AND state='building'",(result['generation'],schema)).rowcount
                        if changed != 1:
                            raise ValueError('Candidate stage missing')
                        source.execute('''INSERT INTO fixture_publication_state(singleton,active_schema,generation) VALUES(TRUE,%s,%s)
                            ON CONFLICT(singleton) DO UPDATE SET active_schema=excluded.active_schema,generation=excluded.generation''',
                            (schema,result['generation']))
                except psycopg.Error:
                    # Commit can succeed before a connection error reaches us.
                    # Only accept success if a fresh connection confirms it.
                    try:
                        with self.factory() as check:
                            _guard(check)
                            confirmed=check.execute('SELECT active_schema,generation FROM fixture_publication_state WHERE singleton').fetchone()
                    except psycopg.Error as exc:
                        raise RuntimeError('Publication outcome unknown; restore required') from exc
                    if confirmed != (schema,result['generation']):
                        raise
                old,self.active=self.active,(schema,replacement)
                replacement=None
                if old is not None:
                    try:
                        old[1].close()
                    except Exception as exc:
                        self.cleanup_errors.append(type(exc).__name__)
                return result['generation']
            finally:
                if replacement is not None:
                    replacement.close()

    def get(self, ident):
        with self.lock:
            if self.active is None: raise RuntimeError('Fixture publisher is not ready')
            return PostgreSQLDocumentReader(lambda:self.target_factory(self.active[0])).get(ident)

    def search(self, query, **kwargs):
        with self.lock:
            if self.active is None: raise RuntimeError('Fixture publisher is not ready')
            with self.target_factory(self.active[0]) as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                return search_feed(conn,self.active[1],query,**kwargs)

    def close(self):
        with self.lock:
            if self.active is not None:
                self.active[1].close()
                self.active=None
