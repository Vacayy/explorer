"""Refresh the candidate's sector_market_* tables from the projection (pipeline.postgres_sector_refresh).

  python scripts/refactor_sector_refresh.py            # REFACTOR_FIXTURE_SCHEMA: the candidate schema to repoint
  python scripts/refactor_sector_refresh.py --rollback # point the views at the base schema again
Prints only counts, latest dates and timings.
"""
import json
import os
import sys

import psycopg

from pipeline import postgres_sector_refresh as refresh

dsn, schema = os.environ['REFACTOR_POSTGRES_DSN'], os.environ['REFACTOR_FIXTURE_SCHEMA']
base = os.environ['REFACTOR_BASE_SCHEMA']
candidate = lambda: psycopg.connect(dsn, options=f'-c search_path={schema}')  # noqa: E731
store_for = lambda store: psycopg.connect(dsn, options=f'-c search_path={store}')  # noqa: E731
with psycopg.connect(dsn, autocommit=True) as admin:
    if sys.argv[1:] == ['--rollback']:
        previous = None
        with candidate() as conn, conn.transaction():
            previous = refresh.current_store(conn)
            refresh.repoint(conn, base)
        if previous != base:
            admin.execute(f'DROP SCHEMA "{previous}" CASCADE')
        print(json.dumps({'views': base, 'dropped': previous if previous != base else None}))
    else:
        projection = '/projection/' + json.load(open('/projection/current.json'))['file']
        result = refresh.refresh(admin, candidate, store_for, projection, base=base)
        changed = {t: (result['before'][t], result['after'][t]) for t in refresh.TABLES if result['before'][t] != result['after'][t]}
        print(json.dumps({'store': result['store'][:26] + '…', 'load_seconds': result['load_seconds'],
                          'total_seconds': result['total_seconds'], 'tables': len(refresh.TABLES),
                          'changed': changed, 'prices': result['after']['sector_market_prices'],
                          'us_prices': result['after']['sector_market_us_prices']}, ensure_ascii=False))
