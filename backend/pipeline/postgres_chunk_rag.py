"""Experimental fixture-only RAG adapter using one PostgreSQL snapshot."""
import sqlite3

from pipeline.postgres_chat_chunks import ChatChunkImportConflict


class PostgreSQLChunkRAG:
    def __init__(self, chunks, rerank):
        self.chunks = chunks
        self.rerank = rerank

    def _check(self, conn):
        current = conn.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
        if not current or str(current[0]) != self.chunks.generation:
            raise ChatChunkImportConflict('document generation changed')

    def chunk_index_ready(self):
        return True

    def search_chunks(self, query, **kwargs):
        return self.chunks.search(query, **kwargs)

    def channel_scope(self, name):
        """Reuse the original source matcher against snapshot metadata only."""
        from pipeline.chat_tools import _coverage, _match_sources
        columns = {
            'blog_sources': ('url', 'blog_name', 'author'),
            'telegram_channels': ('channel_name', 'display_name'),
            'youtube_channels': ('channel_id', 'title', 'handle'),
            'scrap_links': ('doc_id', 'channel'),
            'raw_documents': ('id', 'source_type', 'source_id', 'url', 'published_at'),
        }
        memory = sqlite3.connect(':memory:')
        memory.row_factory = sqlite3.Row
        try:
            with self.chunks.connect() as pg:
                pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                self._check(pg)
                present = {r[0] for r in pg.execute(
                    'SELECT table_name FROM legacy_snapshot_tables WHERE table_name=ANY(%s)', (list(columns),))}
                if present != set(columns):
                    raise ChatChunkImportConflict('channel source tables are missing')
                for table, fields in columns.items():
                    # Names are constants above, not input from the caller.
                    memory.execute(f"CREATE TABLE {table} ({','.join(fields)})")
                    select = ','.join("row_data->>%s" for _ in fields)
                    with pg.cursor(name='channel_' + table) as cursor:
                        cursor.execute(f'SELECT {select} FROM legacy_snapshot_rows WHERE table_name=%s', (*fields, table))
                        while rows := cursor.fetchmany(1000):
                            memory.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in fields)})", rows)
                self._check(pg)
            conds, params, names = _match_sources(memory, name)
            if not conds:
                return None
            where = ' OR '.join(conds)
            ids = {int(row[0]) for row in memory.execute(f'SELECT rd.id FROM raw_documents rd WHERE {where}', params)}
            return ids, names, _coverage(memory, conds, params)
        finally:
            memory.close()

    def entity_scope(self, name):
        """Apply the original entity resolver to PG snapshot metadata and documents."""
        from pipeline.chat_tools import entity_terms, resolve_entity_ex
        memory = sqlite3.connect(':memory:')
        memory.row_factory = sqlite3.Row
        try:
            memory.executescript('''
                CREATE TABLE entities (id INTEGER, type TEXT, name TEXT, aliases TEXT);
                CREATE TABLE entity_keywords (entity_id INTEGER, keyword TEXT, status TEXT);
            ''')
            with self.chunks.connect() as pg:
                pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                self._check(pg)
                required = ['entities', 'entity_keywords', 'entity_links', 'raw_documents']
                present = {r[0] for r in pg.execute(
                    'SELECT table_name FROM legacy_snapshot_tables WHERE table_name=ANY(%s)', (required,))}
                if present != set(required):
                    raise ChatChunkImportConflict('entity source tables are missing')
                for table, fields in (('entities', ('id', 'type', 'name', 'aliases')),
                                      ('entity_keywords', ('entity_id', 'keyword', 'status'))):
                    select = ','.join('row_data->>%s' for _ in fields)
                    with pg.cursor(name='entity_' + table) as cursor:
                        cursor.execute(f'SELECT {select} FROM legacy_snapshot_rows WHERE table_name=%s ORDER BY row_ordinal',
                                       (*fields, table))
                        while rows := cursor.fetchmany(1000):
                            memory.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in fields)})", rows)

                def score_company(eid, residual):
                    rows = pg.execute("SELECT d.row_data->>'id',d.row_data->>'title',d.row_data->>'markdown',"
                                      "d.row_data->>'published_at' FROM legacy_snapshot_rows l "
                                      "JOIN legacy_snapshot_rows d ON d.table_name='raw_documents' "
                                      "AND d.row_data->>'id'=l.row_data->>'doc_id' "
                                      "WHERE l.table_name='entity_links' AND l.row_data->>'entity_id'=%s", (str(eid),)).fetchall()
                    if len(residual) < 2:
                        return sum(bool(r[3]) and r[3][:10] >= memory.execute(
                            "SELECT date('now','-180 days')").fetchone()[0] for r in rows)
                    # Each row is a link, so duplicate links count just as the original join does.
                    fts = sqlite3.connect(':memory:')
                    try:
                        fts.execute('CREATE VIRTUAL TABLE doc_fts USING fts5(title,markdown)')
                        fts.executemany('INSERT INTO doc_fts(title,markdown) VALUES (?,?)', [(r[1], r[2]) for r in rows])
                        return fts.execute('SELECT count(*) FROM doc_fts WHERE doc_fts MATCH ?',
                                           (f'"{residual}"',)).fetchone()[0]
                    finally:
                        fts.close()

                assumptions = {}
                entity = resolve_entity_ex(memory, name, asm=assumptions, score_company=score_company)
                terms = entity_terms(memory, entity) if entity else None
                self._check(pg)
                return (int(entity['id']) if entity else None), terms, assumptions
        finally:
            memory.close()

    def fetch_docs(self, ids):
        if not ids:
            return []
        with self.chunks.connect() as conn:
            self._check(conn)
            rows = conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' "
                                "AND (row_data->>'id')::bigint=ANY(%s)", (ids,)).fetchall()
            self._check(conn)
        docs = {row[0]['id']: row[0] for row in rows}
        fields = ('id', 'source_type', 'source_id', 'title', 'url', 'published_at')
        return [{**{key: docs[i].get(key) for key in fields},
                 'excerpt': (docs[i].get('markdown') or '')[:1200]} for i in ids if i in docs]

    def apply_filters(self, docs, since_days, source, entity_id, doc_ids):
        from pipeline.rag import _filter_with_settings
        with self.chunks.connect() as conn:
            self._check(conn)
            required = {'telegram_channels', 'blog_sources', 'entity_links'}
            present = {row[0] for row in conn.execute(
                'SELECT table_name FROM legacy_snapshot_tables WHERE table_name=ANY(%s)', (list(required),))}
            if present != required:
                raise ChatChunkImportConflict('filter source tables are missing')
            rows = conn.execute("SELECT table_name,row_data FROM legacy_snapshot_rows "
                                "WHERE table_name=ANY(%s)", (['telegram_channels', 'blog_sources'],)).fetchall()
            muted = {'telegram': {r['channel_name'] for table, r in rows
                                  if table == 'telegram_channels' and r.get('is_active') == 0},
                     'blog': [r['url'] for table, r in rows
                              if table == 'blog_sources' and r.get('is_active') == 0]}
            linked = None
            if entity_id:
                linked = {int(row[0]) for row in conn.execute(
                    "SELECT row_data->>'doc_id' FROM legacy_snapshot_rows WHERE table_name='entity_links' "
                    "AND row_data->>'entity_id'=%s", (str(entity_id),))}
            self._check(conn)
        return _filter_with_settings(docs, since_days, source, linked, doc_ids, muted)
