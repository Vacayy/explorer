"""Rebuild experimental detail response cache from PostgreSQL source rows only."""
import json

from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader
from pipeline.postgres_snapshot import SNAPSHOT_LOCK_KEY


def rebuild_details(connection_factory):
    """Atomically replace detail JSON in a disposable fixture; never touch feed rows."""
    with connection_factory() as conn:
        database, schema = conn.execute('SELECT current_database(), current_schema()').fetchone()
        if database != 'fixture' or not schema or not schema.startswith('refactor_fixture_'):
            raise ValueError('Refusing rebuild outside the disposable fixture schema')
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (SNAPSHOT_LOCK_KEY,))
        source_ids = [r[0] for r in conn.execute(
            "SELECT (row_data->>'id')::bigint FROM legacy_snapshot_rows "
            "WHERE table_name='raw_documents' ORDER BY (row_data->>'id')::bigint")]
        projected_ids = [r[0] for r in conn.execute('SELECT id FROM document_projection ORDER BY id')]
        if source_ids != projected_ids:
            raise ValueError('Source and detail projection document IDs differ')
        reader = PostgreSQLRawDocumentReader(connection_factory)
        for doc_id in source_ids:
            document = reader.get_in_transaction(conn, doc_id)
            if document is None:
                raise ValueError('Source document missing during rebuild')
            conn.execute('UPDATE document_projection SET detail_document=%s::jsonb WHERE id=%s',
                         (json.dumps(document.model_dump(mode='json'), ensure_ascii=False), doc_id))
        return len(source_ids)
