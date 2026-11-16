"""Experimental fixture-only RAG adapter using one PostgreSQL snapshot."""
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
