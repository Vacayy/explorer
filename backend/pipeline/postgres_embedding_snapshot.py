"""Preserve existing sqlite-vec embeddings, without computing new vectors.

This stores the original float32 bytes and the content hash in the same fixture
transaction as the document generation. The recorded model is the current code's
expectation; the SQLite vector table does not prove which model created each row.
It is not a search index or live API. The source must have sqlite-vec loaded and
already be in a query-only read transaction.
"""
import re
import math
import struct

from pipeline.search import EMBED_MODEL

_DIMENSIONS = 384


def capture_embeddings(source, destination, generation):
    if not source.in_transaction or source.execute('PRAGMA query_only').fetchone()[0] != 1:
        raise ValueError('A query-only SQLite transaction is required')
    database, schema = destination.execute('SELECT current_database(), current_schema()').fetchone()
    if database != 'fixture' or not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema):
        raise ValueError('Refusing embedding writes outside the disposable fixture schema')
    if source.execute('SELECT count(*) FROM doc_vec v LEFT JOIN raw_documents d ON d.id=v.rowid WHERE d.id IS NULL').fetchone()[0]:
        raise ValueError('Embedding without source document')
    if source.execute('SELECT count(*) FROM doc_vec_hash h LEFT JOIN doc_vec v ON v.rowid=h.rowid WHERE v.rowid IS NULL').fetchone()[0]:
        raise ValueError('Embedding hash without vector')
    destination.execute('TRUNCATE document_embeddings, document_embedding_metadata')
    count = stale = unknown_hash = 0
    with destination.cursor().copy('COPY document_embeddings (document_id, embedding, content_hash) FROM STDIN') as copy:
        for ident, embedding, hash_id, content_hash, source_hash in source.execute('''SELECT v.rowid, v.embedding, h.rowid, h.content_hash, d.content_hash
            FROM doc_vec v LEFT JOIN doc_vec_hash h ON h.rowid=v.rowid
            JOIN raw_documents d ON d.id=v.rowid'''):
            if hash_id is None or len(embedding) != _DIMENSIONS * 4:
                raise ValueError('Missing embedding hash or invalid vector size')
            if not all(math.isfinite(value[0]) for value in struct.iter_unpack('<f', embedding)):
                raise ValueError('Embedding contains a non-finite value')
            if source_hash is None:
                unknown_hash += 1
            elif content_hash != source_hash:
                stale += 1
            copy.write_row((ident, bytes(embedding), content_hash))
            count += 1
    destination.execute('''INSERT INTO document_embedding_metadata
        (generation_id, expected_model, dimensions, vector_count, stale_count, source_hash_missing_count)
        VALUES (%s,%s,%s,%s,%s,%s)''', (generation, EMBED_MODEL, _DIMENSIONS, count, stale, unknown_hash))
    return count


def embedding_for_current_snapshot(connection, document_id):
    """Read only when preserved vectors match the current document generation."""
    row = connection.execute('''SELECT e.generation_id, s.generation_id
        FROM document_embedding_metadata e CROSS JOIN snapshot_metadata s
        WHERE e.singleton AND s.singleton''').fetchone()
    if row is None or row[0] != row[1]:
        raise ValueError('Embeddings do not match the current document snapshot')
    result = connection.execute('SELECT embedding, content_hash FROM document_embeddings WHERE document_id=%s',
                                (document_id,)).fetchone()
    return (bytes(result[0]), result[1]) if result else None
