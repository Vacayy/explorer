"""Single-process fixture publisher; never activates a production database."""
import threading
import uuid
from pathlib import Path
from psycopg import sql
from pipeline.postgres_graph_fixture import _guard
from pipeline.postgres_note_overlay_fixture import copy_with_note_changes
from pipeline.postgres_search_snapshot import SearchSnapshot
from pipeline.postgres_search_feed import search_feed
from pipeline.postgres_document_read import PostgreSQLDocumentReader


class FixturePublisher:
    def __init__(self, factory, source_schema, target_factory, index_factory=SearchSnapshot):
        self.factory=factory
        self.source_schema=source_schema
        self.target_factory=target_factory
        self.index_factory=index_factory
        self.lock=threading.RLock()
        self.active=None
        self.pending_cleanup=set()

    def _drop(self, schema):
        with self.factory() as conn:
            _guard(conn)
            conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))

    def publish(self):
        schema='refactor_fixture_'+uuid.uuid4().hex
        index=None
        with self.lock:
            self.cleanup_retired()
            try:
                with self.factory() as conn:
                    _guard(conn)
                    conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
                    conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
                    conn.execute((Path(__file__).resolve().parents[1]/'refactor_sql/document_projection.sql').read_text())
                with self.factory() as conn:
                    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                    result=copy_with_note_changes(conn,self.source_schema,schema)
                    rows=conn.execute("SELECT (row_data->>'id')::bigint,row_data->>'title',row_data->>'markdown' "
                                      "FROM legacy_snapshot_rows WHERE table_name='raw_documents' ORDER BY row_ordinal").fetchall()
                    vectors=[(ident,bytes(value)) for ident,value in conn.execute('SELECT document_id,embedding FROM document_embeddings ORDER BY document_id')]
                    index=self.index_factory(result['generation'],rows,vectors)
                    if index.generation != str(result['generation']):
                        raise ValueError('Replacement index generation mismatch')
                previous=self.active
                self.active=(schema,index)
                if previous:
                    previous[1].close()
                    self.pending_cleanup.add(previous[0])
                    try:
                        self.cleanup_retired()
                    except Exception:
                        pass  # Remains visible in pending_cleanup; next publish retries.
                return result['generation']
            except BaseException:
                if index is not None and (self.active is None or self.active[1] is not index):
                    index.close()
                if self.active is None or self.active[0] != schema:
                    self._drop(schema)
                raise

    def cleanup_retired(self):
        with self.lock:
            for schema in tuple(self.pending_cleanup):
                self._drop(schema)
                self.pending_cleanup.remove(schema)

    def get(self, ident):
        with self.lock:
            if self.active is None: raise RuntimeError('Fixture is not ready')
            return PostgreSQLDocumentReader(lambda:self.target_factory(self.active[0])).get(ident)

    def search(self, query, **kwargs):
        with self.lock:
            if self.active is None: raise RuntimeError('Fixture is not ready')
            with self.target_factory(self.active[0]) as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                return search_feed(conn,self.active[1],query,**kwargs)

    def close(self):
        with self.lock:
            if self.active:
                schema,index=self.active
                self.active=None
                index.close()
                self.pending_cleanup.add(schema)
            self.cleanup_retired()
