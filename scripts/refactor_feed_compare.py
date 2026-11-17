"""Read-only comparison before an isolated feed work copy is allowed to publish."""
import itertools
import sqlite3
import sys

import refactor_collect_trial as trial


def main():
    tables = ('raw_documents', 'enrichments', 'entity_links', 'entities', 'entity_keywords', 'entity_relations')
    work = sqlite3.connect('file:/trial/work.db?mode=ro', uri=True)
    work.row_factory = sqlite3.Row
    diagnose = '--diagnose' in sys.argv
    with trial._pg() as pg, pg.transaction():
        for table in tables:
            local = work.execute(f'SELECT * FROM "{table}" ORDER BY id')
            with pg.cursor(name=f'feed_compare_{table}') as remote:
                remote.itersize = 100
                remote.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s "
                               "ORDER BY (row_data->>'id')::bigint", (table,))
                if diagnose:
                    remote_rows = iter(remote)
                    a, b = next(local, None), next(remote_rows, None)
                    added = removed = changed = 0
                    while a is not None or b is not None:
                        if b is None or (a is not None and a['id'] < b[0]['id']):
                            added += 1
                            a = next(local, None)
                        elif a is None or b[0]['id'] < a['id']:
                            removed += 1
                            b = next(remote_rows, None)
                        else:
                            changed += dict(a) != b[0]
                            a, b = next(local, None), next(remote_rows, None)
                    print(f'{table}: work_only={added} pg_only={removed} changed={changed}')
                    count = added + removed + changed
                else:
                    count = sum(1 for a, b in itertools.zip_longest(local, remote)
                                if a is None or b is None or dict(a) != b[0])
                    print(f'{table}: differences={count}')
            if count and not diagnose:
                raise SystemExit('Feed copy differs from candidate; do not publish')
    work.close()


if __name__ == '__main__':
    main()
