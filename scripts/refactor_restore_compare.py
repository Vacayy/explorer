"""Compare a restored disposable PG fixture after rebuilding its timeline caches.

Both databases must be private throwaway fixtures; no original SQLite is accessed.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
import psycopg

from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader
from pipeline.postgres_rebuild_timeline import rebuild_source_timeline
from pipeline.postgres_rebuild_system_timeline import rebuild_system_timeline
from pipeline.postgres_timeline_sources import PostgreSQLTimelineSources


def main():
    schema = os.environ['REFACTOR_FIXTURE_SCHEMA']
    if os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema):
        raise ValueError('Only disposable fixture schemas are supported')
    dsns = [os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_RESTORED_DSN']]
    for expected, dsn in zip(('pg', 'pg-restore'), dsns, strict=True):
        p = psycopg.conninfo.conninfo_to_dict(dsn)
        if (p.get('host'), p.get('dbname'), p.get('user')) != (expected, 'fixture', 'fixture'):
            raise ValueError('Refusing a non-fixture database')
    def factory(dsn):
        return lambda: psycopg.connect(dsn, options=f'-c search_path={schema}')
    original, restored = map(factory, dsns)
    # Compare inventories and the metadata required by source rebuild.
    def inventory(factory):
        with factory() as c:
            return (dict(c.execute('SELECT table_name,row_count FROM legacy_snapshot_tables').fetchall()),
                    dict(c.execute('SELECT table_name,count(*) FROM legacy_snapshot_rows GROUP BY table_name').fetchall()),
                    c.execute('SELECT count(*) FROM timeline_source_metadata').fetchone()[0],
                    c.execute('SELECT count(*) FROM document_entity_order').fetchone()[0])
    counts_match = inventory(original) == inventory(restored)
    if not counts_match:
        raise ValueError('Restored inventory differs')
    with restored() as c:
        c.execute('DELETE FROM timeline_source_projection')
        c.execute('DELETE FROM timeline_system_projection')
    source_count = rebuild_source_timeline(restored)
    system_count = rebuild_system_timeline(restored)
    left, right = PostgreSQLTimelineSources(original), PostgreSQLTimelineSources(restored)
    until = datetime.now(timezone.utc).isoformat()
    cases = {'sources': {'scope': 'sources'}, 'sources_page2': {'scope': 'sources', 'page': 2},
             'telegram': {'scope': 'sources', 'source': 'telegram'}, 'blog': {'scope': 'sources', 'source': 'blog'},
             'youtube': {'scope': 'sources', 'source': 'youtube'}, 'mixed': {'scope': 'all'},
             'system': {'scope': 'system'}, 'person': {'scope': 'system', 'kind': 'person'},
             'company': {'scope': 'system', 'kind': 'company'}, 'transcript': {'scope': 'system', 'kind': 'transcript'},
             'trade': {'scope': 'system', 'kind': 'trade'}, 'narrative': {'scope': 'system', 'kind': 'narrative'},
             'report': {'scope': 'system', 'kind': 'report'}, 'scenario': {'scope': 'system', 'kind': 'scenario'}}
    matches = {}
    for name, params in cases.items():
        a, b = left.timeline(until=until, **params), right.timeline(until=until, **params)
        matches[name] = a.has_more == b.has_more and [x.model_dump() for x in a.items] == [x.model_dump() for x in b.items]
    channel_match = left.channels(until=until, include_owner_read_state=True).model_dump() == right.channels(until=until, include_owner_read_state=True).model_dump()
    sample_ids = [item.document.id for item in left.timeline(until=until, scope='sources').items[:10] if item.document]
    a, b = PostgreSQLRawDocumentReader(original), PostgreSQLRawDocumentReader(restored)
    detail_match = all(a.get(doc_id).model_dump() == b.get(doc_id).model_dump() for doc_id in sample_ids)
    report = {'inventory_match': counts_match, 'source_rebuilt': source_count, 'system_rebuilt': system_count,
              'timeline_cases_match': matches, 'channels_match': channel_match,
              'detail_samples': len(sample_ids), 'detail_samples_match': detail_match}
    print(json.dumps(report), flush=True)
    return 0 if all((counts_match, all(matches.values()), channel_match, detail_match)) else 1


if __name__ == '__main__':
    sys.exit(main())
