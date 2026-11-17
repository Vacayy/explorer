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


def run(script, argv, factory, *, record, source, projection_dir='/projection', database_host='pg'):
    """Run `script` with `argv`; returns the stored counts. `record`: the job_runs name the script leaves."""
    from fastapi import FastAPI
    from pipeline.postgres_legacy_projection import LegacyProjection, write_connection_var
    from routers.postgres_legacy_read_fixture import _offline, install
    from routers.postgres_owner_legacy_fixture import _Borrowed
    projection = LegacyProjection(factory, projection_dir, external=True)
    install(FastAPI(), projection, database_host=database_host)  # guard, get_connection → projection, saved data
    import database
    database.init_db = lambda *args, **kwargs: None  # the projection's schema is fixed; upkeep is the collector's
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
        runs = conn.execute('SELECT job, status FROM temp.job_runs WHERE id > ?' + (' AND job=?' if record else ''),
                            (floor, record) if record else (floor,)).fetchall()
        if record and not runs:
            raise HeldBack(f'job record {record}: missing')
        failed = [f"{row['job']} {row['status']}" for row in runs if row['status'] != 'ok']
        if failed:
            raise HeldBack(f'job record {", ".join(failed)}')
        with factory() as pg, pg.transaction():
            return {'overrides': overrides.apply(pg, before, overrides.rows(conn), source=source),
                    'graph': graph.publish(pg, graph_before, graph.snapshot(conn), run_id=source),
                    'runs': job_runs.capture(pg, conn, floor, source)}
    finally:
        conn.close()
