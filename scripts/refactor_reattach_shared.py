"""Bring the shared collector file up to PG before reattaching it (COLLECT_SHARED_WORK back to 1).

While detached, nothing wrote that file: the feed published from its own file (with PG's graph rows caught up there)
and the isolated jobs published to PG without mirroring. Turning the switch off on a stale file would refresh the feed
from it (losing what the feed published) and leave the old prices for the jobs that still read it. So, with every
collector stopped and in one SQLite transaction on the shared file:

1. the feed's document and graph rows above the shared file's floors are appended (rows both files have must be
   equal) and the floors move to them, with the Telegram grouping marks;
2. each table an isolated job published during the detached period (PG collect_runs since `--since`, their tables
   and the shared-key tables) is replaced by the projection's copy, which is PG's;
3. refused unless the projection shows PG's current version and collected tables, and the result passes
   integrity_check. Nothing is written on any refusal; the shared file stays as it was.

  python /app/scripts/refactor_reattach_shared.py --since '2026-11-22 03:00:00'   # job 'reattach': /trial, /feed ro
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

FEED_TABLES = (('raw_documents', 'document_floor'), ('enrichments', None), ('entity_links', None),
               ('entities', 'entity_floor'), ('entity_keywords', 'keyword_floor'), ('entity_relations', 'relation_floor'))


def append_feed(feed, target):
    """{table: rows appended} from the feed file above the target's floors (inside the caller's transaction)."""
    from refactor_feed_sync import append_group_marks
    floors = dict(target.execute('SELECT name, value FROM candidate_publish_floor'))
    for table, floor in FEED_TABLES:
        if floor and target.execute(f'SELECT COALESCE(max(id),0) FROM "{table}"').fetchone()[0] != floors[floor]:
            raise ValueError(f'{table} has unpublished rows in the shared file')
    feed_floors = dict(feed.execute('SELECT name, value FROM candidate_publish_floor'))
    for table, floor in FEED_TABLES:
        if floor and feed.execute(f'SELECT COALESCE(max(id),0) FROM "{table}"').fetchone()[0] != feed_floors[floor]:
            raise ValueError(f'{table} has unpublished rows in the feed file')
    appended = {}
    for table, _floor in FEED_TABLES:
        columns = [r[1] for r in feed.execute(f'PRAGMA table_info("{table}")')]
        if columns != [r[1] for r in target.execute(f'PRAGMA table_info("{table}")')] or columns[0] != 'id':
            raise ValueError(f'{table} schemas differ')
        start = target.execute(f'SELECT COALESCE(max(id),0) FROM "{table}"').fetchone()[0]
        overlap = feed.execute(f'SELECT * FROM "{table}" WHERE id > ? - 1000 AND id <= ? ORDER BY id', (start, start)).fetchall()
        mine = target.execute(f'SELECT * FROM "{table}" WHERE id > ? - 1000 AND id <= ? ORDER BY id', (start, start)).fetchall()
        if overlap != mine:
            raise ValueError(f'{table}: the files differ below the shared floor')
        rows = feed.execute(f'SELECT * FROM "{table}" WHERE id > ? ORDER BY id', (start,)).fetchall()
        target.executemany(f'INSERT INTO "{table}" VALUES ({",".join("?" * len(columns))})', rows)
        appended[table] = len(rows)
    for table, floor in FEED_TABLES:
        if floor:
            target.execute('UPDATE candidate_publish_floor SET value=(SELECT COALESCE(max(id),0) FROM "%s") WHERE name=?'
                           % table, (floor,))
    appended['telegram_group_marks'] = append_group_marks(feed, target)
    return appended


def realign(target, tables):
    """{table: rows} after replacing each table by the attached projection's (PG's) copy."""
    counts = {}
    for table in tables:
        mine = [r[1] for r in target.execute(f'PRAGMA table_info("{table}")')]
        theirs = {r[1] for r in target.execute(f'PRAGMA projection.table_info("{table}")')}
        if not mine or not theirs:
            raise ValueError(f'{table} is missing from a file')
        columns = ','.join(f'"{c}"' for c in mine if c in theirs)
        target.execute(f'DELETE FROM main."{table}"')
        target.execute(f'INSERT INTO main."{table}" ({columns}) SELECT {columns} FROM projection."{table}"')
        counts[table] = target.execute(f'SELECT count(*) FROM main."{table}"').fetchone()[0]
    return counts


def published_tables(pg, since):
    """The tables of the isolated jobs that published since `since` (shared-key tables included: they are listed)."""
    import refactor_isolated_jobs as jobs
    labels = {label for (label,) in pg.execute(
        "SELECT DISTINCT label FROM collect_runs WHERE started_at >= %s AND (outcome LIKE 'applied%%' OR "
        "outcome LIKE 'partial%%')", (since,))}
    tables = {t for label in labels & set(jobs.TABLES) for t in jobs.TABLES[label]}
    if 'prices' in labels:
        tables.add('signals')  # its 52-week highs
    return sorted(tables)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--since', required=True, help='UTC start of the detached period (collect_runs.started_at)')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    import refactor_collect_trial as trial
    from pipeline import postgres_live_tables
    from pipeline.postgres_legacy_projection import projection_version
    pg = trial._pg()
    manifest = json.loads(Path('/projection/current.json').read_text())
    if manifest['version'] != projection_version(pg) or manifest.get('collection') != postgres_live_tables.versions(pg)[1]:
        raise SystemExit('the projection does not show PG yet: retry after its next build')
    tables = published_tables(pg, args.since)
    target = sqlite3.connect(trial.WORK, isolation_level=None)
    feed = sqlite3.connect('file:/feed/work.db?mode=ro', uri=True)
    try:
        target.execute('ATTACH DATABASE ? AS projection', (f'file:/projection/{manifest["file"]}?mode=ro&immutable=1',))
        target.execute('BEGIN IMMEDIATE')
        try:
            result = {'feed': append_feed(feed, target), 'tables': realign(target, tables)}
            if target.execute('PRAGMA main.integrity_check').fetchone()[0] != 'ok':
                raise ValueError('integrity check failed')
            if args.dry_run:
                raise KeyboardInterrupt
            target.execute('COMMIT')
        except KeyboardInterrupt:
            target.execute('ROLLBACK')
            result['dry_run'] = True
        except BaseException:
            target.execute('ROLLBACK')
            raise
    finally:
        feed.close()
        target.close()
    print(json.dumps({'reattach': result, 'projection': manifest['file']}))


if __name__ == '__main__':
    main()
