"""Import exact conversation-search chunks into a disposable PG generation."""
import os
import re
import sqlite3
import threading
import uuid


class ChatChunkImportConflict(RuntimeError):
    pass


def import_chat_chunks(source, target, *, document_ids=None, batch_size=500):
    """Copy source chunks/vectors without rebuilding or touching live schemas.

    ``source`` is a consistent SQLite snapshot with sqlite-vec loaded. A subset
    can be selected for tests; the metadata records that it is incomplete.
    """
    database, schema = target.execute('SELECT current_database(),current_schema()').fetchone()
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or database != 'fixture' or
            not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema)):
        raise ValueError('Disposable fixture schema required')
    if not 1 <= batch_size <= 2000:
        raise ValueError('invalid batch size')
    ids = None if document_ids is None else sorted(set(document_ids))
    if ids is not None and (not ids or len(ids) > 400 or any(not isinstance(i, int) or i < 1 for i in ids)):
        raise ValueError('invalid document selection')
    source.execute('PRAGMA query_only=ON')
    where = '' if ids is None else ' WHERE c.doc_id IN (' + ','.join('?' for _ in ids) + ')'
    params = () if ids is None else tuple(ids)
    source_docs = {}
    for row in source.execute('SELECT DISTINCT r.id,r.source_type,r.url,r.title,r.published_at,r.content_hash '
                              'FROM doc_chunks c JOIN raw_documents r ON r.id=c.doc_id' + where, params):
        source_docs[row[0]] = tuple(row[1:])
    if ids is not None and set(source_docs) != set(ids):
        raise ChatChunkImportConflict('selected document has no source chunks')

    with target.transaction():
        target.execute('LOCK TABLE chat_chunk_projection,chat_chunk_metadata IN ACCESS EXCLUSIVE MODE')
        if target.execute('SELECT EXISTS(SELECT 1 FROM chat_chunk_projection) OR EXISTS(SELECT 1 FROM chat_chunk_metadata)').fetchone()[0]:
            raise ChatChunkImportConflict('target chunk store is not empty')
        generation = target.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
        if not generation:
            raise ChatChunkImportConflict('document generation is missing')
        pg_docs = {}
        for start in range(0, len(source_docs), 400):
            batch = list(source_docs)[start:start + 400]
            for ident, raw in target.execute("SELECT (row_data->>'id')::bigint,row_data FROM legacy_snapshot_rows "
                                             "WHERE table_name='raw_documents' AND (row_data->>'id')::bigint=ANY(%s)", (batch,)):
                pg_docs[ident] = raw
        fields = ('source_type', 'url', 'title', 'published_at', 'content_hash')
        missing = source_docs.keys() - pg_docs.keys()
        mismatch = [i for i, values in source_docs.items() if i in pg_docs and
                    any(value != pg_docs[i].get(key) for key, value in zip(fields, values))]
        if missing or mismatch:
            raise ChatChunkImportConflict(f'document mismatch: missing={len(missing)}, changed={len(mismatch)}')
        projected = {r[0] for r in target.execute('SELECT id FROM document_projection WHERE id=ANY(%s)', (list(source_docs),))}
        if projected != source_docs.keys():
            raise ChatChunkImportConflict('document projection is incomplete')

        cursor = source.execute('SELECT c.id,c.doc_id,c.idx,c.text,c.prefix,c.content_hash,v.embedding '
                                'FROM doc_chunks c LEFT JOIN chunk_vec v ON v.rowid=c.id' + where + ' ORDER BY c.id', params)
        count = stale = 0
        with target.cursor() as out:
            while rows := cursor.fetchmany(batch_size):
                prepared = []
                for row in rows:
                    row = tuple(row)
                    if row[1] not in source_docs or row[6] is None or len(row[6]) != 1536:
                        raise ChatChunkImportConflict('orphan chunk or invalid embedding')
                    stale += row[5] != source_docs[row[1]][-1]
                    prepared.append((*row[:6], bytes(row[6])))
                out.executemany('INSERT INTO chat_chunk_projection '
                                '(id,document_id,chunk_index,text,prefix,content_hash,embedding) '
                                'VALUES (%s,%s,%s,%s,%s,%s,%s)', prepared)
                count += len(prepared)
        target.execute('INSERT INTO chat_chunk_metadata '
                       '(generation_id,chunk_count,document_count,stale_chunk_count,complete) VALUES (%s,%s,%s,%s,%s)',
                       (generation[0], count, len(source_docs), stale, ids is None))
    return {'chunks': count, 'documents': len(source_docs), 'stale_chunks': stale, 'complete': ids is None}


class PostgreSQLChunkSearch:
    """Disposable in-memory search index reconstructed from one PG generation.

    PG is the source of truth; the private SQLite FTS/vector index is an
    ephemeral cache so the original search_chunks ranking can be reused.
    """
    def __init__(self, connect, model_provider, *, allow_partial=False):
        import sqlite_vec
        self.connect = connect
        self.model_provider = model_provider
        self.lock = threading.RLock()
        self.uri = f'file:pg-chat-chunks-{uuid.uuid4().hex}?mode=memory&cache=shared'
        self.keeper = sqlite3.connect(self.uri, uri=True, check_same_thread=False)
        try:
            self.keeper.enable_load_extension(True)
            sqlite_vec.load(self.keeper)
            self.keeper.enable_load_extension(False)
            self.keeper.executescript('''
              CREATE TABLE doc_chunks(id INTEGER PRIMARY KEY,doc_id INTEGER,idx INTEGER,text TEXT,prefix TEXT,content_hash TEXT);
              CREATE VIRTUAL TABLE chunk_fts USING fts5(prefix,text);
              CREATE VIRTUAL TABLE chunk_vec USING vec0(embedding float[384]);
            ''')
            with connect() as pg:
                pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                database, schema = pg.execute('SELECT current_database(),current_schema()').fetchone()
                if (database != 'fixture' or not schema or
                        not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema)):
                    raise ValueError('Disposable fixture schema required')
                metadata = pg.execute('SELECT generation_id,chunk_count,complete FROM chat_chunk_metadata WHERE singleton').fetchone()
                active = pg.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
                if not metadata or not active or metadata[0] != active[0] or (not metadata[2] and not allow_partial):
                    raise ChatChunkImportConflict('chunk generation is incomplete or stale')
                self.generation = str(metadata[0])
                with pg.cursor(name='chat_chunks_index') as cursor:
                    cursor.execute('SELECT id,document_id,chunk_index,text,prefix,content_hash,embedding FROM chat_chunk_projection ORDER BY id')
                    while rows := cursor.fetchmany(500):
                        self.keeper.executemany('INSERT INTO doc_chunks VALUES(?,?,?,?,?,?)', [tuple(r[:6]) for r in rows])
                        self.keeper.executemany('INSERT INTO chunk_fts(rowid,prefix,text) VALUES(?,?,?)', [(r[0], r[4], r[3]) for r in rows])
                        self.keeper.executemany('INSERT INTO chunk_vec(rowid,embedding) VALUES(?,?)', [(r[0], bytes(r[6])) for r in rows])
                self.keeper.commit()
                if self.keeper.execute('SELECT count(*) FROM doc_chunks').fetchone()[0] != metadata[1]:
                    raise ChatChunkImportConflict('chunk index count differs from metadata')
        except Exception:
            self.keeper.close()
            raise

    def _connection(self):
        import sqlite_vec
        conn = sqlite3.connect(self.uri, uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn

    def get_connection(self):
        return self._connection()

    def vector_connection(self):
        return self._connection()

    def get_model(self, *, local_files_only=True):
        return self.model_provider(local_files_only=local_files_only)

    def search(self, query, **kwargs):
        from pipeline.chunks import search_chunks
        with self.lock:
            with self.connect() as pg:
                current = pg.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
            if not current or str(current[0]) != self.generation:
                raise ChatChunkImportConflict('document generation changed')
            result = search_chunks(query, runtime=self, **kwargs)
            with self.connect() as pg:
                current = pg.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
            if not current or str(current[0]) != self.generation:
                raise ChatChunkImportConflict('document generation changed')
            return result

    def close(self):
        with self.lock:
            self.keeper.close()
