"""Scheduled legacy computations (narratives, contradictions, knowledge promotion, …) on the candidate, one-shot.

The same path as the computation buttons (routers.postgres_owner_overrides_fixture): the unchanged legacy script
runs in this process on one projection connection whose decision and computation tables, graph tables and job_runs
are writable TEMP copies, under the same in-process network guard and saved-data rules as the API's reads (model
calls run as CLI subprocesses). Only if the script's own job record is 'ok' are its changes stored, in one PG
transaction: override rows, the graph diff (by id, conflicts kept) and its run records. A write to any other table
hits the read-only projection and fails the run (fail closed). Collected tables are never written here; they
come from the collection jobs.
"""
import runpy
import sqlite3
import sys

from pipeline import postgres_candidate_job_runs as job_runs
from pipeline import postgres_graph_compute as graph
from pipeline import postgres_owner_overrides as overrides


def _shadowed(conn, table):
    return conn.execute("SELECT 1 FROM temp.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


class HeldBack(RuntimeError):
    """The computation did not prove itself; nothing stored."""


class Skipped(RuntimeError):
    """The script's own admin flag is off (its run_job recorded 'skipped'); nothing to store."""


def _cap_model_calls(limit):
    """At most `limit` model calls in this run (each llm._execute: one call, its fallback included); the next is
    refused and the run is held back. Returns the counter."""
    from pipeline import llm
    execute, made = llm._execute, [0]

    def capped(*args, **kwargs):
        if made[0] >= limit:
            raise RuntimeError(f'model call cap {limit} reached')
        made[0] += 1
        return execute(*args, **kwargs)
    llm._execute = capped
    return made


def wait_for_projection(factory, projection_dir, *, timeout=600, poll=5):
    """Until the builder's file carries every change PG holds now (a chain step reads the documents the intake
    step just published). Returns the seconds waited; raises HeldBack at the timeout."""
    import json
    import time
    from pathlib import Path
    from pipeline.postgres_legacy_projection import projection_version
    with factory() as pg:
        wanted = projection_version(pg)
    generation, counter = wanted.rsplit(':', 1)
    started = time.monotonic()
    while True:
        try:
            built = json.loads((Path(projection_dir) / 'current.json').read_text())['version']
        except (OSError, ValueError, KeyError):
            built = ''
        built_generation, _, built_counter = built.rpartition(':')
        if built_generation == generation and built_counter.isdigit() and int(built_counter) >= int(counter):
            return round(time.monotonic() - started)
        if time.monotonic() - started > timeout:
            raise HeldBack(f'projection still at {built or "none"}, PG at {wanted}')
        time.sleep(poll)


def run(script, argv, factory, *, record, source, projection_dir='/projection', database_host='pg', max_calls=20):
    """Run `script` with `argv`; returns the stored counts. `record`: the job_runs name the script leaves."""
    from fastapi import FastAPI
    from pipeline.postgres_legacy_projection import LegacyProjection, write_connection_var
    from routers.postgres_legacy_read_fixture import _offline, install
    from routers.postgres_owner_legacy_fixture import _Borrowed
    import os
    wait = int(os.environ.get('COLLECT_PROJECTION_WAIT', '600'))  # 0: a clone test, whose projection is the live one
    waited = wait_for_projection(factory, projection_dir, timeout=wait) if wait else None
    projection = LegacyProjection(factory, projection_dir, external=True)
    install(FastAPI(), projection, database_host=database_host)  # guard, get_connection → projection, saved data
    import database
    database.init_db = lambda *args, **kwargs: None  # the projection's schema is fixed; upkeep is the collector's
    from pipeline import postgres_legacy_embeddings
    postgres_legacy_embeddings.install(factory)  # doc_vec is not in the projection: PG document vectors, as the API
    calls = _cap_model_calls(max_calls)
    conn, _version = projection.write_connection(graph.GRAPH + ('job_runs',))
    refused = set()  # collected (read-only) tables the script tried to write: named in the failure

    def authorizer(action, table, _detail, database, _trigger):
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) and database == 'main' \
                and table and not table.startswith('sqlite_') and not _shadowed(conn, table):
            refused.add(table)
        return sqlite3.SQLITE_OK
    conn.set_authorizer(authorizer)
    try:
        before, graph_before, floor = overrides.rows(conn), graph.snapshot(conn), job_runs.floor(conn)
        token, offline = write_connection_var.set(_Borrowed(conn)), _offline.set(True)
        sys.argv = [script, *argv]
        try:
            runpy.run_path(script, run_name='__main__')
        except SystemExit as exc:
            if exc.code not in (0, None):
                raise HeldBack(f'exit {exc.code}') from None
        except sqlite3.OperationalError as exc:
            if refused:
                raise RuntimeError(f'writes collected tables {sorted(refused)}') from exc
            raise
        finally:
            write_connection_var.reset(token)
            _offline.reset(offline)
        if calls[0] >= max_calls:
            raise HeldBack(f'model call cap {max_calls} reached (a later call was refused)')
        runs = conn.execute('SELECT job, status FROM temp.job_runs WHERE id > ?' + (' AND job=?' if record else ''),
                            (floor, record) if record else (floor,)).fetchall()
        if record and not runs:
            raise HeldBack(f'job record {record}: missing')
        if runs and all(row['status'] == 'skipped' for row in runs):
            raise Skipped(', '.join(sorted({row['job'] for row in runs})) + ' flag off')  # an admin choice, not a failure
        failed = [f"{row['job']} {row['status']}" for row in runs if row['status'] != 'ok']
        if failed:
            raise HeldBack(f'job record {", ".join(failed)}')
        with factory() as pg, pg.transaction():
            return {'waited_s': waited, 'overrides': overrides.apply(pg, before, overrides.rows(conn), source=source),
                    'graph': graph.publish(pg, graph_before, graph.snapshot(conn), run_id=source),
                    'runs': job_runs.capture(pg, conn, floor, source)}
    finally:
        conn.close()
