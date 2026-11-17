"""Commit a feed publication receipt in the same PG transaction as its changes.

This module is preparation only. The caller owns the durable local intent and must
not acknowledge it until the receipt is visible and local bookkeeping completes.
"""
import uuid

from pipeline import postgres_collect_runs

LABEL = 'feed-publication-receipt'


def _token(value):
    value = str(value)
    if str(uuid.UUID(value)) != value:
        raise ValueError('A canonical UUID receipt is required')
    return value


def committed(conn, token):
    token = _token(token)
    rows = conn.execute('SELECT count(*) FROM collect_runs WHERE label=%s AND detail=%s',
                        (LABEL, token)).fetchone()[0]
    if rows > 1:
        raise RuntimeError('Duplicate feed publication receipts require investigation')
    return rows == 1


def publish_once(conn, token, started, publish):
    """Run publish and record its token atomically; on restart a receipt skips republishing."""
    token = _token(token)
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', (token,))
        if committed(conn, token):
            return False
        publish()
        postgres_collect_runs.record(conn, LABEL, started, f'applied: {token}')
    return True
