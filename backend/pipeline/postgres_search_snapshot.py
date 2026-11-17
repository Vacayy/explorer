"""Disposable search prototype for one PostgreSQL document generation.

The index is private, in memory, and never registered with the live API. SQLite
FTS5 and sqlite-vec retain the existing tokenization and distance semantics;
rebuilding vec0 can still change the order of equal-distance results.
"""
import math
import re
import sqlite3
import struct
import threading

from pipeline.search import _fts_query


class SearchSnapshot:
    def __init__(self, generation, documents, embeddings=()):
        import sqlite_vec
        self.generation = str(generation)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        try:
            self.db.enable_load_extension(True)
            sqlite_vec.load(self.db)
            self.db.enable_load_extension(False)
            self.db.execute('CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, title TEXT, markdown TEXT)')
            self.db.execute("CREATE VIRTUAL TABLE doc_fts USING fts5(title, markdown, content='raw_documents', content_rowid='id')")
            self.db.execute('CREATE VIRTUAL TABLE doc_vec USING vec0(embedding float[384])')
            self.db.executemany('INSERT INTO raw_documents VALUES (?,?,?)', documents)
            self.db.execute("INSERT INTO doc_fts(doc_fts) VALUES('rebuild')")
            self.db.executemany('INSERT INTO doc_vec(rowid,embedding) VALUES (?,?)', embeddings)
        except Exception:
            self.db.close()
            raise

    @classmethod
    def from_postgres(cls, connection, *, lexical_only=False, allow_stale=False):
        database, schema = connection.execute('SELECT current_database(), current_schema()').fetchone()
        if database != 'fixture' or not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema):
            raise ValueError('Only a disposable fixture is supported')
        if (connection.execute('SHOW transaction_isolation').fetchone()[0] not in ('repeatable read', 'serializable')
                or connection.execute('SHOW transaction_read_only').fetchone()[0] != 'on'):
            raise ValueError('A read-only repeatable-read transaction is required')
        generation, count = connection.execute(
            'SELECT generation_id, document_count FROM snapshot_metadata WHERE singleton').fetchone()
        metadata = connection.execute('SELECT generation_id, vector_count, stale_count, source_hash_missing_count '
                                      'FROM document_embedding_metadata WHERE singleton').fetchone()
        if not lexical_only:
            if metadata is None or metadata[0] != generation:
                raise ValueError('Embeddings are missing or do not match the current generation')
            if (metadata[2] or metadata[3]) and not allow_stale:
                raise ValueError('Embeddings are missing or do not match the current generation')
            if connection.execute('SELECT count(*) FROM document_embeddings').fetchone()[0] != metadata[1]:
                raise ValueError('Embedding inventory differs from generation metadata')
            if not allow_stale and connection.execute("SELECT EXISTS(SELECT 1 FROM document_embeddings e "
                "LEFT JOIN legacy_snapshot_rows r ON r.table_name='raw_documents' AND r.row_data->>'id'=e.document_id::text "
                "WHERE e.content_hash IS NULL OR r.row_data->>'content_hash' IS NULL "
                "OR e.content_hash IS DISTINCT FROM r.row_data->>'content_hash')").fetchone()[0]:
                raise ValueError('Embeddings are missing or do not match current documents')
        # Named cursors keep PostgreSQL transfer bounded; the resulting search
        # index itself is intentionally an in-memory prototype.
        with connection.cursor(name='fixture_search_documents') as docs, connection.cursor(name='fixture_search_embeddings') as vecs:
            docs.execute("SELECT (row_data->>'id')::bigint,row_data->>'title',row_data->>'markdown',row_data->>'content_hash' "
                         "FROM legacy_snapshot_rows WHERE table_name='raw_documents' ORDER BY row_ordinal")
            hashes = {}
            def documents():
                for ident, title, markdown, content_hash in docs:
                    if allow_stale and not lexical_only and content_hash is not None:
                        hashes[ident] = content_hash
                    yield ident, title, markdown
            if lexical_only:
                index = cls(generation, documents())
            else:
                if allow_stale:
                    vecs.execute('SELECT document_id,embedding,content_hash FROM document_embeddings ORDER BY document_id')
                    embeddings = ((ident, bytes(blob)) for ident, blob, content_hash in vecs
                                  if content_hash is not None and hashes.get(ident) == content_hash)
                else:
                    vecs.execute('SELECT document_id,embedding FROM document_embeddings ORDER BY document_id')
                    embeddings = ((ident, bytes(blob)) for ident, blob in vecs)
                index = cls(generation, documents(), embeddings)
        vector_count = index.db.execute('SELECT count(*) FROM doc_vec').fetchone()[0] if not lexical_only else 0
        expected_vectors = vector_count if allow_stale else (metadata[1] if not lexical_only else 0)
        if index.db.execute('SELECT count(*) FROM raw_documents').fetchone()[0] != count or \
                (not lexical_only and (vector_count != expected_vectors or vector_count > metadata[1])):
            index.close()
            raise ValueError('Incomplete search generation')
        index.excluded_vectors = metadata[1] - vector_count if not lexical_only and allow_stale else 0
        return index

    def search(self, query, *, vector=None, k=100):
        if not isinstance(query, str) or not 1 <= k <= 100:
            raise ValueError('Invalid search request')
        if vector is not None and (not isinstance(vector, bytes) or len(vector) != 1536 or
                                   not all(math.isfinite(x[0]) for x in struct.iter_unpack('<f', vector))):
            raise ValueError('Invalid query embedding')
        with self.lock:
            fts = [row[0] for row in self.db.execute(
                'SELECT rowid FROM doc_fts WHERE doc_fts MATCH ? ORDER BY rank LIMIT 40', (_fts_query(query),))]
            vec = [] if vector is None else [row[0] for row in self.db.execute(
                'SELECT rowid FROM doc_vec WHERE embedding MATCH ? AND k=40 ORDER BY distance', (vector,))]
        ranks = {}
        for group in (fts, vec):
            for position, ident in enumerate(group):
                ranks[ident] = ranks.get(ident, 0) + 1 / (60 + position)
        guaranteed = set(fts[:max(1, k // 2)]) | set(vec[:max(1, k // 2)])
        order = sorted(ranks, key=lambda ident: -ranks[ident])
        order = [ident for ident in order if ident in guaranteed] + [ident for ident in order if ident not in guaranteed]
        return [{'doc_id': ident, 'score': ranks[ident]} for ident in order[:k]]

    def close(self):
        with self.lock:
            self.db.close()
