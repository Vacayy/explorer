"""Retrieval jobs for the single-path compute worker: queries in, related documents out.

Features that need the legacy chunk search and reranker (too large for the preview API) put a job
here; the worker (`pipeline.postgres_compute_worker`) runs the job's handler with the legacy
retrieval pointed at the chunk index and the projection. Document claims are the first kind;
AI-answer evidence search is meant to use the same ledger.
"""
import sqlite3

from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import _guard


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('retrieval_jobs')").fetchone()[0] is not None:
            raise ValueError('Retrieval jobs already initialized')
        conn.execute("CREATE TABLE retrieval_jobs (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,kind TEXT NOT NULL,"
                     "subject TEXT NOT NULL,request JSONB NOT NULL,result JSONB,status TEXT NOT NULL DEFAULT 'queued' "
                     "CHECK(status IN ('queued','done','failed')),error TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
                     'updated_at TIMESTAMPTZ NOT NULL DEFAULT now())')
        conn.execute("CREATE INDEX retrieval_jobs_queued ON retrieval_jobs (created_at) WHERE status='queued'")


def enqueue(conn, kind, subject, request):
    return conn.execute('INSERT INTO retrieval_jobs(kind,subject,request) VALUES (%s,%s,%s) RETURNING id',
                        (kind, subject, Jsonb(request))).fetchone()[0]


def legacy_retrieval(chunks_path, projection_path):
    """Point the unchanged legacy retrieval modules at the chunk index with the projection attached."""
    import database
    from pipeline import chunks, rag, search, visibility

    def connection():
        conn = sqlite3.connect(chunks_path, timeout=30)
        conn.execute('ATTACH DATABASE ? AS projection', (f'file:{projection_path}?mode=ro',))
        conn.row_factory = sqlite3.Row
        return conn

    for module in (database, chunks, rag, search):  # each bound get_connection at import
        module.get_connection = connection
    # The owner's personal mute is not applied without per-user identity (all collected material shows),
    # and retrieval shown to users does not drop unverified sources (scrap) either (PM decision).
    visibility.get_muted = lambda conn: {'telegram': set(), 'blog': []}
    visibility.UNVERIFIED_SOURCES = frozenset()
    return connection


def run_queued(factory, handlers):
    """Run every queued job whose kind has a handler; `handler(factory, request) -> result` may raise."""
    with factory() as conn:
        jobs = conn.execute("SELECT id,kind,request FROM retrieval_jobs WHERE status='queued' AND kind=ANY(%s) "
                            'ORDER BY created_at', (list(handlers),)).fetchall()
    done = []
    for ident, kind, request in jobs:
        try:
            result, status, error = handlers[kind](factory, request), 'done', None
        except Exception as exc:  # noqa: BLE001 - kept with its reason; not retried automatically
            result, status, error = None, 'failed', f'{type(exc).__name__}: {str(exc)[:300]}'
        with factory() as conn:
            conn.execute('UPDATE retrieval_jobs SET status=%s,result=%s,error=%s,updated_at=now() WHERE id=%s',
                         (status, Jsonb(result) if result is not None else None, error, ident))
        done.append((ident, kind, status))
    return done
