"""Replace an isolated fixture snapshot after host and VM capacity checks."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3

import psycopg
from pipeline.postgres_capacity import require_snapshot_capacity
from pipeline.postgres_snapshot import load_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--schema', required=True)
    parser.add_argument('--host-probe', type=Path, required=True)
    parser.add_argument('--vm-probe', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    dsn = os.environ['REFACTOR_POSTGRES_DSN']
    params = psycopg.conninfo.conninfo_to_dict(dsn)
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or
            (params.get('host'), params.get('dbname'), params.get('user')) != ('pg', 'fixture', 'fixture') or
            not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', args.schema)):
        raise ValueError('Only a disposable isolated fixture is accepted')
    # A single mount cannot stand in for both the VM and the host filesystem.
    if args.host_probe.stat().st_dev == args.vm_probe.stat().st_dev:
        raise ValueError('Host and VM probes must be distinct filesystem mounts')
    def pg():
        return psycopg.connect(dsn, options=f'-c search_path={args.schema}')
    source = sqlite3.connect(args.source.resolve(strict=True).as_uri() + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    try:
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        def capacity_check(sqlite_source, target):
            return require_snapshot_capacity(sqlite_source, target, host_probe=args.host_probe, vm_probe=args.vm_probe)
        with pg() as target:
            result = capacity_check(source, target)
        if not args.check_only:
            result = load_snapshot(source, pg, snapshot_at=datetime.now(timezone.utc).isoformat(), capacity_check=capacity_check)
        print(json.dumps(result), flush=True)
    finally:
        source.close()


if __name__ == '__main__':
    main()
