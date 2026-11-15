"""Disposable, isolated comparison using a read-only existing SQLite copy.

No real contents or credentials are printed. This is not an operational migration.
The caller must provide a private disposable fixture PostgreSQL database.
Large SQLite sorts need a private, disk-backed SQLITE_TMPDIR with enough space;
a small tmpfs may result in SQLITE_FULL. Remove scratch data after the trial.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import sqlite3
import statistics
import sys
import tempfile
import time
import traceback
import uuid
from unittest.mock import patch

import psycopg
from psycopg import sql

from pipeline.document_read import _read_sqlite_document
from pipeline.postgres_document_read import PostgreSQLDocumentReader
from pipeline.postgres_raw_document_read import PostgreSQLRawDocumentReader
from pipeline.postgres_timeline_sources import PostgreSQLTimelineSources
from pipeline.timeline import timeline
from pipeline.postgres_snapshot import LEGACY_TABLES, load_snapshot
from routers import spine_feed


class _ReadConnection(sqlite3.Connection):
    def close(self):
        pass


def _feed(conn, *, source=None, page=1, size=20):
    with patch.object(spine_feed, 'get_connection', return_value=conn):
        return spine_feed.get_feed(q=None, source=source, stock=None, industry=None,
                                   topic=None, page=page, size=size, days=None, sort='relevance')


def run(source_path: Path, media: Path, dsn: str, *, retain: bool = False,
        retain_on_mismatch: bool = False) -> dict:
    if os.getenv('REFACTOR_TEST_DISPOSABLE') != '1':
        raise ValueError('Disposable fixture opt-in required')
    params = psycopg.conninfo.conninfo_to_dict(dsn)
    if (params.get('host'), params.get('dbname'), params.get('user')) != ('pg', 'fixture', 'fixture'):
        raise ValueError('Only the isolated fixture database is accepted')
    source = sqlite3.connect(source_path.resolve(strict=True).as_uri() + '?mode=ro',
                             uri=True, factory=_ReadConnection)
    source.row_factory = sqlite3.Row
    schema = 'refactor_fixture_' + uuid.uuid4().hex
    created = False
    retain_completed = False
    try:
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        created = True
        def pg():
            return psycopg.connect(dsn, options=f'-c search_path={schema}')
        ddl = Path(__file__).resolve().parents[1] / 'backend/refactor_sql/document_projection.sql'
        with pg() as conn:
            conn.execute(ddl.read_text())
        start = time.monotonic()
        result = load_snapshot(source, pg, snapshot_at=datetime.now(timezone.utc).isoformat())
        result['load_seconds'] = round(time.monotonic() - start, 3)
        result['worker_peak_rss_mib'] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
        reader = PostgreSQLDocumentReader(pg)
        with pg() as conn:
            manifest = {r[0]: r[1] for r in conn.execute('SELECT table_name,row_count FROM legacy_snapshot_tables')}
            counts = {r[0]: r[1] for r in conn.execute('SELECT table_name,count(*) FROM legacy_snapshot_rows GROUP BY table_name')}
            result['postgres_database_mib'] = round(conn.execute('SELECT pg_database_size(current_database())').fetchone()[0] / 1048576, 1)
        result['source_table_counts_match'] = all(
            manifest.get(name) == source.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            and counts.get(name, 0) == manifest.get(name) for name in LEGACY_TABLES)
        sample_values_match = True
        samples = 0
        with pg() as conn:
            for name in LEGACY_TABLES:
                for ordinal, row in enumerate(source.execute(f'SELECT * FROM "{name}" LIMIT 3')):
                    target = conn.execute('SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s AND row_ordinal=%s',
                                          (name, ordinal)).fetchone()
                    samples += 1
                    sample_values_match &= target is not None and target[0] == dict(row)
        result['source_rows_sampled'] = samples
        result['source_row_values_match'] = sample_values_match
        cases = [(None, 1), (None, 2), ('telegram', 1), ('blog', 1), ('news', 1),
                 ('article', 1), ('youtube', 1), ('transcript', 1), ('people', 1)]
        comparisons = {}
        expected_by_case = {}
        for name, page in cases:
            key = (name or 'all') + ':' + str(page)
            old = _feed(source, source=name, page=page)
            new = reader.list(source=name, page=page)
            same = (old.total == new.total and
                    [d.model_dump() for d in old.items] == [d.model_dump() for d in new.items])
            comparisons[key] = same
            expected_by_case[(name, page)] = old
        result['feed_cases_match'] = comparisons
        ids = []
        for feed in expected_by_case.values():
            ids.extend(x.id for x in feed.items[:2])
        unique = list(dict.fromkeys(ids))
        result['detail_samples'] = len(unique)
        result['detail_samples_match'] = all(
            (old := _read_sqlite_document(source, i)) is not None and
            (new := reader.get(i)) is not None and old.model_dump() == new.model_dump() for i in unique)
        raw_reader = PostgreSQLRawDocumentReader(pg)
        differences = []
        for i in unique:
            old, new = _read_sqlite_document(source, i), raw_reader.get(i)
            if old is None or new is None:
                differences.append({'source_type': 'unavailable', 'fields': ['missing']})
                continue
            old_value, new_value = old.model_dump(), new.model_dump()
            fields = sorted(k for k in old_value if old_value[k] != new_value[k])
            if fields:
                differences.append({'source_type': old.source_type, 'fields': fields})
        result['raw_detail_samples_match'] = not differences
        result['raw_detail_differences'] = differences
        # Compare the actual source-lane timeline, not the separate document feed.
        timeline_reader = PostgreSQLTimelineSources(pg)
        fixed_until = datetime.now(timezone.utc).isoformat()
        with pg() as conn:
            channel_row = conn.execute("SELECT channel FROM timeline_source_projection GROUP BY channel ORDER BY count(*) DESC LIMIT 1").fetchone()
        timeline_cases = {'all': {}, 'page2': {'page': 2}, 'telegram': {'source': 'telegram'},
                          'blog': {'source': 'blog'}, 'youtube': {'source': 'youtube'},
                          'empty': {'channel': 'telegram:__fixture_missing__'}}
        if channel_row:
            timeline_cases['channel'] = {'channel': channel_row[0]}
        timeline_matches = {}
        for name, params in timeline_cases.items():
            expected = timeline(source, scope='sources', until=fixed_until, **params)
            actual = timeline_reader.timeline(until=fixed_until, **params)
            timeline_matches[name] = (expected.has_more == actual.has_more and
                                      [i.model_dump() for i in expected.items] == [i.model_dump() for i in actual.items])
        result['source_timeline_cases_match'] = timeline_matches
        # Copy a few real attachment bytes to an isolated temporary directory;
        # source volume is read-only and no original paths or content are logged.
        attached, missing = 0, 0
        root = media.resolve(strict=True)
        with tempfile.TemporaryDirectory(prefix='refactor-media-') as tmp:
            for row in source.execute("SELECT media_json FROM raw_documents WHERE media_json IS NOT NULL AND media_json NOT IN ('','[]','null') LIMIT 30"):
                try:
                    refs = json.loads(row[0])
                except (ValueError, TypeError):
                    missing += 1
                    continue
                for ref in refs if isinstance(refs, list) else []:
                    if not isinstance(ref, str):
                        missing += 1
                        continue
                    path = (root / ref).resolve()
                    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                        missing += 1
                        continue
                    body = path.read_bytes()
                    out = Path(tmp) / str(attached)
                    out.write_bytes(body)
                    if out.read_bytes() != body:
                        raise AssertionError('Attachment sample mismatch')
                    attached += 1
                    if attached == 3:
                        break
                if attached == 3:
                    break
        result['attachment_bytes_compared'] = attached
        result['attachment_missing_or_unsupported'] = missing
        # Same source snapshot and same PostgreSQL contents, warm repeated reads.
        # The new side reads a precomputed projection, not normalized PG tables.
        timings = {'sqlite_ms': [], 'postgres_ms': []}
        with pg() as shared:
            shared.autocommit = True
            @contextmanager
            def pooled():
                with shared.transaction():
                    yield shared
            pooled_reader = PostgreSQLDocumentReader(pooled)
            for _ in range(3):
                for name, page in [(None, 1), ('telegram', 1), ('blog', 1), ('transcript', 1)]:
                    start = time.perf_counter(); _feed(source, source=name, page=page)
                    timings['sqlite_ms'].append((time.perf_counter() - start) * 1000)
                    start = time.perf_counter(); pooled_reader.list(source=name, page=page)
                    timings['postgres_ms'].append((time.perf_counter() - start) * 1000)
        result['warm_feed_measurement'] = {
            'calls_each': len(timings['sqlite_ms']),
            'sqlite_median_ms': round(statistics.median(timings['sqlite_ms']), 2),
            'postgres_median_ms': round(statistics.median(timings['postgres_ms']), 2),
            'sqlite_max_ms': round(max(timings['sqlite_ms']), 2),
            'postgres_max_ms': round(max(timings['postgres_ms']), 2),
            'scope': 'warm, connection reuse; PostgreSQL precomputed projection',
        }
        if retain and all((result['source_table_counts_match'], result['source_row_values_match'],
                           all(result['feed_cases_match'].values()), result['detail_samples_match'],
                           all(result['source_timeline_cases_match'].values()),
                           result['raw_detail_samples_match'] or retain_on_mismatch)):
            result['fixture_schema'] = schema
            retain_completed = True
        return result
    finally:
        sqlite3.Connection.close(source)
        if created and not retain_completed:
            with psycopg.connect(dsn) as conn:
                conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--media', type=Path, required=True)
    parser.add_argument('--retain', action='store_true', help='retain a successful disposable fixture for UI testing')
    parser.add_argument('--retain-on-mismatch', action='store_true', help='retain a mismatched fixture only for local debugging')
    args = parser.parse_args()
    if args.retain_on_mismatch and not args.retain:
        parser.error('--retain-on-mismatch requires --retain')
    try:
        result = run(args.source, args.media, os.environ['REFACTOR_POSTGRES_DSN'],
                     retain=args.retain, retain_on_mismatch=args.retain_on_mismatch)
    except Exception as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        location = [(Path(f.filename).name, f.name, f.lineno) for f in frames[-4:]]
        print('full trial failed:', type(exc).__name__,
              'sqlite_code:', getattr(exc, 'sqlite_errorname', None),
              'postgres_code:', getattr(exc, 'sqlstate', None),
              'location:', location, file=sys.stderr, flush=True)
        return 1
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
