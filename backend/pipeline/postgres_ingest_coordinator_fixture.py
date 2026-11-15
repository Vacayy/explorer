"""Single-process coordinator for the disposable note-only feed/search fixture.

All readers and the rebuilder must use this instance. This is not a
multi-process deployment, durable index, or a production synchronization scheme.
"""
import threading
from pipeline.postgres_document_read import PostgreSQLDocumentReader
from pipeline.postgres_ingest_rebuild_fixture import rebuild
from pipeline.postgres_search_feed import search_feed
from pipeline.postgres_search_snapshot import SearchSnapshot


class FixtureCoordinator:
    def __init__(self, factory, index_factory=SearchSnapshot):
        self.factory = factory
        self.index_factory = index_factory
        self.reader = PostgreSQLDocumentReader(factory)
        self.lock = threading.RLock()
        self.index = None

    def rebuild(self):
        replacement = None
        with self.lock:
            try:
                with self.factory() as conn:
                    generation = rebuild(conn)
                    rows = conn.execute("SELECT (row_data->>'id')::bigint,row_data->>'title',row_data->>'markdown' "
                                        "FROM legacy_snapshot_rows WHERE table_name='raw_documents' ORDER BY row_ordinal").fetchall()
                    vectors = [(ident, bytes(value)) for ident, value in conn.execute(
                        'SELECT document_id,embedding FROM document_embeddings ORDER BY document_id')]
                    replacement = self.index_factory(generation, rows, vectors)
                    if replacement.generation != str(generation):
                        raise ValueError('Replacement index has wrong generation')
                previous, self.index = self.index, replacement
                if previous:
                    previous.close()
                return generation
            except BaseException:
                if replacement is not None and replacement is not self.index:
                    replacement.close()
                raise

    def list(self, **kwargs):
        with self.lock:
            if self.index is None:
                raise RuntimeError('Fixture is not ready')
            return self.reader.list(**kwargs)

    def search(self, query, **kwargs):
        with self.lock:
            if self.index is None:
                raise RuntimeError('Fixture is not ready')
            with self.factory() as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                return search_feed(conn, self.index, query, **kwargs)

    def close(self):
        with self.lock:
            if self.index:
                self.index.close()
                self.index = None
