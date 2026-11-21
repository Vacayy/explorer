"""Bring the collector work copy's graph up to PG before a feed run, so the feed never hands out an ID PG already has.

Graph rows can reach PG without passing through the collector file: the computation paths (narrative compute button,
scheduled computations, scenarios: pipeline.postgres_graph_compute) add entities and relations under the next IDs of
the projection. The collector file then still issues those IDs to its own new entities, and the feed publication
stops with 'entities IDs were taken while collecting' (runs 365 on 11/20 and 445 on 11/21).

Here, in one SQLite transaction, PG's entities, entity keywords and relations above the file's published floors are
appended as they are, and the floors move past them. It refuses (nothing changed, the feed stays held) when the file
has unpublished graph rows of its own, when PG has documents above the file's document floor (a feed publication
that was not synchronized back), or when an appended row does not fit the file (a unique key, a missing endpoint).

  python /app/scripts/refactor_feed_graph.py     # in a job container: PG, and the collector file at /trial
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

TABLES = (('entities', 'entity_floor'), ('entity_keywords', 'keyword_floor'), ('entity_relations', 'relation_floor'))


def catch_up(pg, work):
    """{table: rows appended}; raises ValueError (and rolls back) when the file cannot take PG's rows as they are."""
    floors = dict(work.execute('SELECT name, value FROM candidate_publish_floor'))
    try:
        work.execute('BEGIN IMMEDIATE')
        newer_docs = pg.execute("SELECT count(*) FROM legacy_snapshot_rows WHERE table_name='raw_documents' "
                                "AND (row_data->>'id')::bigint > %s", (floors['document_floor'],)).fetchone()[0]
        if newer_docs:
            raise ValueError(f'PG has {newer_docs} documents above the file\'s floor: synchronize the feed first')
        appended = {}
        for table, floor in TABLES:
            if work.execute(f'SELECT COALESCE(max(id),0) FROM "{table}"').fetchone()[0] != floors[floor]:
                raise ValueError(f'{table} has unpublished rows in the file')
            columns = [row[1] for row in work.execute(f'PRAGMA table_info("{table}")')]
            rows = [row for (row,) in pg.execute(
                "SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s AND (row_data->>'id')::bigint > %s "
                "ORDER BY (row_data->>'id')::bigint", (table, floors[floor]))]
            extra = sorted({key for row in rows for key in row} - set(columns))
            if extra:
                raise ValueError(f'{table} rows in PG have columns the file lacks: {extra}')
            try:
                work.executemany(f'INSERT INTO "{table}" ({",".join(columns)}) VALUES ({",".join("?" * len(columns))})',
                                 [[row.get(c) for c in columns] for row in rows])
            except sqlite3.IntegrityError as exc:
                raise ValueError(f'{table} rows from PG do not fit the file: {exc}') from None
            if rows:
                work.execute('UPDATE candidate_publish_floor SET value=? WHERE name=?', (rows[-1]['id'], floor))
            appended[table] = len(rows)
        missing = work.execute('SELECT count(*) FROM entity_relations r WHERE r.id > ? AND (NOT EXISTS (SELECT 1 FROM '
                               'entities e WHERE e.id=r.src_id) OR NOT EXISTS (SELECT 1 FROM entities e WHERE e.id=r.dst_id))',
                               (floors['relation_floor'],)).fetchone()[0]
        if missing:
            raise ValueError(f'{missing} appended relations point to entities the file lacks')
        if work.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('integrity check failed')
        work.commit()
        return appended
    except BaseException:
        work.rollback()
        raise


def main():
    import refactor_collect_trial as trial
    work = sqlite3.connect(trial.WORK, isolation_level=None)
    try:
        appended = catch_up(trial._pg(), work)
    finally:
        work.close()
    print(json.dumps({'feed_graph': appended}))


if __name__ == '__main__':
    main()
