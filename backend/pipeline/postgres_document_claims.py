"""Read captured document claims from a disposable PostgreSQL generation."""
import json
import time

from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader

STALE_SECONDS = 600


def claims_state(connection, doc_id, *, now=None):
    if connection.execute("SELECT 1 FROM legacy_snapshot_tables WHERE table_name='doc_claims'").fetchone() is None:
        raise ValueError('Document claims were not captured')
    document = connection.execute(
        "SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' AND row_data->>'id'=%s",
        (str(doc_id),),
    ).fetchone()
    if document is None:
        return None
    saved = connection.execute(
        "SELECT row_data FROM legacy_snapshot_rows WHERE table_name='doc_claims' AND row_data->>'doc_id'=%s",
        (str(doc_id),),
    ).fetchone()
    row = saved[0] if saved else {}
    status = row.get('status')
    if status is None or (status in ('ok', 'skipped') and row.get('content_hash') != document[0].get('content_hash')):
        status = 'none'
    elif status == 'running' and (time.time() if now is None else now) - (row.get('updated_at') or 0) > STALE_SECONDS:
        status = 'failed'
    claims = json.loads(row['payload'])['claims'] if status == 'ok' and row.get('payload') else []
    reader = PostgreSQLRawDocumentReader(None)
    metadata = {}
    for claim in claims:
        for related in claim['related']:
            ident = related['id']
            if ident not in metadata:
                raw = connection.execute(
                    "SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' AND row_data->>'id'=%s",
                    (str(ident),),
                ).fetchone()
                detail = reader.get_in_transaction(connection, ident)
                metadata[ident] = None if raw is None or detail is None else {
                    'source_type': raw[0]['source_type'], 'title': raw[0]['title'],
                    'published_at': raw[0]['published_at'], 'channel': detail.channel,
                }
    result = []
    for claim in claims:
        related = [{**entry, **metadata[entry['id']]} for entry in claim['related'] if metadata[entry['id']] is not None]
        if related:
            result.append({'claim': claim['claim'], 'related': related})
    error = row.get('error') if status == 'failed' else None
    if status == 'failed' and not error:
        error = '논점 정리가 중단되었습니다. 다시 시도해 주세요.'
    return {'status': status, 'error': error, 'claims': result}
