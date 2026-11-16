"""Re-embed documents whose content changed after the snapshot (single-path preview).

Uses the legacy recipe (`search.build_index`: title + first 2000 markdown chars,
same local model) and keeps the base generation untouched: fresh vectors live
in `document_embedding_overrides`, which replace the base row for the same
document in the `document_embeddings` view, so the vector count is unchanged.
"""
from pipeline.postgres_graph_fixture import _guard


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('document_embedding_overrides')").fetchone()[0] is not None:
            raise ValueError('Embedding overrides already initialized')
        definition = conn.execute("SELECT pg_get_viewdef(to_regclass('document_embeddings'),true)").fetchone()[0]
        conn.execute('CREATE TABLE document_embedding_overrides AS SELECT * FROM document_embeddings WHERE false')
        conn.execute('ALTER TABLE document_embedding_overrides ADD PRIMARY KEY (document_id)')
        conn.execute(f'''CREATE OR REPLACE VIEW document_embeddings AS
            SELECT b.document_id,b.embedding,b.content_hash FROM ({definition.rstrip().rstrip(";")}) b
            WHERE NOT EXISTS (SELECT 1 FROM document_embedding_overrides o WHERE o.document_id=b.document_id)
            UNION ALL SELECT document_id,embedding,content_hash FROM document_embedding_overrides''')


def stale_documents(conn):
    """Listed vectors whose stored hash no longer matches the visible document."""
    return conn.execute("""
        SELECT (r.row_data->>'id')::bigint, r.row_data->>'title', substr(COALESCE(r.row_data->>'markdown',''),1,2000),
               r.row_data->>'content_hash'
        FROM document_embeddings e JOIN legacy_snapshot_rows r
          ON r.table_name='raw_documents' AND r.row_data->>'id'=e.document_id::text
        WHERE e.content_hash IS DISTINCT FROM r.row_data->>'content_hash' ORDER BY 1""").fetchall()


def refresh(conn, model, serialize):
    """Embed stale documents once and store them; returns the refreshed ids."""
    _guard(conn)
    rows = stale_documents(conn)
    if not rows:
        return []
    vectors = list(model.embed([f'{title}\n{markdown or ""}' for _, title, markdown, _ in rows]))
    with conn.transaction():
        for (ident, _, _, digest), vector in zip(rows, vectors):
            conn.execute('INSERT INTO document_embedding_overrides VALUES (%s,%s,%s) ON CONFLICT (document_id) '
                         'DO UPDATE SET embedding=excluded.embedding,content_hash=excluded.content_hash',
                         (ident, serialize(vector), digest))
    return [row[0] for row in rows]
