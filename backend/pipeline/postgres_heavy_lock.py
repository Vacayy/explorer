"""One memory-heavy job at a time on the candidate's VM (architect #3 6948497320, PM 6948470184).

The projection builder, the heavy scheduled jobs and the compute worker all connect to the same PG, so one session
advisory lock serializes them: whoever holds it keeps its connection open for the whole job, and a process or
container that dies drops the connection and with it the lock (no stale lock to clear).
"""
import time

KEY = "hashtextextended('explorer-heavy', 0)"


def try_lock(conn):
    """True when this session now holds the heavy lock (keep `conn` open until the job ends)."""
    return conn.execute(f'SELECT pg_try_advisory_lock({KEY})').fetchone()[0]


def unlock(conn):
    conn.execute(f'SELECT pg_advisory_unlock({KEY})')


def wait_lock(conn, *, seconds, every=30):
    """Try until `seconds` have passed; returns the seconds waited, or None when the lock stayed busy."""
    started = time.monotonic()
    while True:
        if try_lock(conn):
            return round(time.monotonic() - started)
        if time.monotonic() - started + every > seconds:
            return None
        time.sleep(every)
