"""Sync rehearsal R2, B approach (agent-whiteboard sync-rehearsal-runbook.md; architect #3 6942322316, 6943495251).

The stand-in 'MacBook latest' (/rehearsal/source.db) sits where a collector file would: the documents and graph rows it
changed since the 11-14 base (/base/stock_explorer.db, read only) are published as one large collection run, every
supplement table it holds is replaced, and the sector market tables are reloaded from it — each step with its time.
These steps are the freeze window's candidate side; the projection, vectors and chunks follow afterwards (R5).
Runs in a one-shot container on the rehearsal schema only (REFACTOR_FIXTURE_SCHEMA); prints counts and seconds.

  python /app/scripts/refactor_rehearsal_r2.py
"""
import json
import os
import sqlite3
import sys
import time

import psycopg

SOURCE, BASE, ORIGIN = '/rehearsal/source.db', '/base/stock_explorer.db', '/projection/current.db'
FLOOR_TABLES = (('document_floor', 'raw_documents'), ('entity_floor', 'entities'), ('keyword_floor', 'entity_keywords'),
                ('relation_floor', 'entity_relations'))


def readonly(path, *, immutable=False):
    conn = sqlite3.connect(f"file:{path}?mode=ro{'&immutable=1' if immutable else ''}", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def main():
    from pipeline import postgres_collected_changes_fixture as changes
    from pipeline.postgres_collector_bridge import refresh_supplement
    dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
    if schema == os.environ.get('TRIAL_LIVE_SCHEMA'):
        raise SystemExit('The rehearsal schema, never the live one')
    connect = lambda: psycopg.connect(dsn, options=f'-c search_path={schema}')  # noqa: E731
    steps, out = {}, {}

    # R1.5 (architect #3 6943703383): the candidate's pre-band ids must already be renumbered; then the candidate's
    # duplicates of the MacBook's rows (same natural key) are withdrawn and their references moved, inside the freeze.
    from pipeline import postgres_id_remap as remap
    started = time.monotonic()
    with connect() as pg:
        base_schema = __import__('pipeline.postgres_sector_refresh', fromlist=['x']).base_schema(pg)
        left = remap.plan(pg, base_schema)
        if left:
            raise SystemExit(f'{len(left)} candidate rows still in the MacBook id range: renumber first')
        source = readonly(SOURCE)
        out['merge'] = remap.merge(pg, source)
        source.close()
    steps['merge_same_source'] = round(time.monotonic() - started, 1)

    started = time.monotonic()
    base = readonly(BASE, immutable=True)
    floors = {name: base.execute(f'SELECT COALESCE(max(id),0) FROM {table}').fetchone()[0] for name, table in FLOOR_TABLES}
    before, graph = changes.capture(base, floors['document_floor']), changes.capture_graph(base)
    base.close()
    steps['capture_base'] = round(time.monotonic() - started, 1)

    started = time.monotonic()
    work, origin = readonly(SOURCE), readonly(ORIGIN)
    with connect() as pg:
        result = changes.publish_run(pg, work, origin, before, run_id='rehearsal R2', graph=graph, **floors)
        out['documents'] = {'added': len(result['added']), 'revised': len(result['revised']), 'kept': len(result['kept']),
                            'graph': result['graph']}
        out['unprocessed'] = changes.unprocessed(pg)
    steps['publish_documents_graph'] = round(time.monotonic() - started, 1)

    from pipeline import postgres_supplement_preserve as preserve
    started = time.monotonic()
    with connect() as pg:
        captured, state, excluded = preserve.capture(pg, work)  # the candidate's collected rows the MacBook file lacks
    out['supplement_excluded'] = excluded
    steps['capture_candidate_supplement'] = round(time.monotonic() - started, 1)
    started = time.monotonic()
    with connect() as pg:
        names = [row[0] for row in pg.execute('SELECT table_name FROM legacy_supplement_tables ORDER BY 1')]
        present = {row[0] for row in work.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tables = [name for name in names if name in present]
        counts = refresh_supplement(pg, SOURCE, tables)
    out['supplement'] = {'tables': len(tables), 'rows': sum(counts.values()),
                         'not_in_source': sorted(set(names) - present)}
    steps['replace_supplement'] = round(time.monotonic() - started, 1)
    started = time.monotonic()
    with connect() as pg:
        out['supplement_preserved'] = preserve.restore(pg, captured, state)
        # Gate (architect #3 6945482451 item 4): every accumulating candidate-only row is back, or the run stops.
        for table, rows in captured.items():
            back = out['supplement_preserved'][table]['added_back']
            if back != len(rows):
                raise SystemExit(f'{table}: {back} of {len(rows)} candidate rows added back')
    steps['restore_candidate_supplement'] = round(time.monotonic() - started, 1)
    work.close()
    origin.close()

    started = time.monotonic()
    from pipeline import postgres_sector_refresh as sector
    with connect() as conn:
        base_schema = sector.base_schema(conn)
    with psycopg.connect(dsn, autocommit=True) as admin:
        result = sector.refresh(admin, connect, lambda store: psycopg.connect(dsn, options=f'-c search_path={store}'),
                                SOURCE, base=base_schema, drop_previous=False)  # the live schema still reads it
    out['sector'] = {'prices': result['after']['sector_market_prices'], 'load_seconds': result['load_seconds'],
                     'store': result['store'], 'previous_kept': result['previous']}
    steps['reload_sector_market'] = round(time.monotonic() - started, 1)

    out['seconds'] = steps
    out['freeze_side_total'] = round(sum(steps.values()), 1)
    print(json.dumps(out, ensure_ascii=False, default=str))


if __name__ == '__main__':
    sys.exit(main())
