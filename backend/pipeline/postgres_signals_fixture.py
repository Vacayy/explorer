"""Read-only, disposable experiment for the existing signal list contract."""
import os
import re
from routers.spine_signals import _row_to_item


def signals_items(conn, *, since, signal_type=None):
    database,schema=conn.execute('SELECT current_database(),current_schema()').fetchone()
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or database != 'fixture' or
            not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',schema)):
        raise ValueError('Disposable fixture schema required')
    if (conn.execute('SHOW transaction_isolation').fetchone()[0] != 'repeatable read' or
            conn.execute('SHOW transaction_read_only').fetchone()[0] != 'on'):
        raise ValueError('Read-only repeatable-read required')
    rows=conn.execute("""
      SELECT s.row_data,e.row_data FROM legacy_snapshot_rows s
      JOIN legacy_snapshot_rows e ON e.table_name='entities' AND e.row_data->>'id'=s.row_data->>'entity_id'
      WHERE s.table_name='signals' AND s.row_data->>'date'>=%s
        AND (%s::text IS NULL OR s.row_data->>'signal_type'=%s)
        AND (%s::text IS DISTINCT FROM 'theme_surge' OR s.row_data->>'date'=(
          SELECT max(s2.row_data->>'date') FROM legacy_snapshot_rows s2
          WHERE s2.table_name='signals' AND s2.row_data->>'signal_type'=s.row_data->>'signal_type'
            AND s2.row_data->>'entity_id'=s.row_data->>'entity_id'))
      ORDER BY s.row_data->>'date' DESC,(s.row_data->>'id')::bigint DESC
    """,(since,signal_type,signal_type,signal_type)).fetchall()
    return [_row_to_item({**signal,'entity_name':entity['name'],'stock_code':entity.get('aliases')}) for signal,entity in rows]
