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
