"""Peer monitor publications kept current (architect #3 6942709181, PM 6942635135).

The candidate's Peer screens read the sector_market_peer_runtime view, which the base snapshot load fixed to one
captured bundle (the base overlay). The peer job runs the MacBook collector unchanged (scripts/refresh_peer_monitor.py)
on its own state volume, reads the publication the way the legacy API does (routers.peers.read_runtime), and hands the
result here: it is recorded in a candidate-owned ledger (candidate_peer_runtime), checked against what the view shows
now (the company set may not fall below half, the price date may not go back), and the view is pointed at the new row
in one transaction. The base overlay is never written; each row keeps the view definition it replaced, so a rollback
restores exactly the previous read path.
"""
from psycopg import sql
from psycopg.types.json import Jsonb

SHRINK_LIMIT = 0.5
LEDGER = ('CREATE TABLE IF NOT EXISTS candidate_peer_runtime (id BIGSERIAL PRIMARY KEY, payload JSONB NOT NULL, '
          'as_of TEXT NOT NULL, companies INTEGER NOT NULL, published_at TEXT, previous_view TEXT NOT NULL, '
          'rolled_back_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now())')


def shown(conn):
    """The Peer runtime the candidate shows now (None without one)."""
    row = conn.execute('SELECT payload FROM sector_market_peer_runtime WHERE singleton').fetchone()
    return row[0] if row else None


def _view(conn):
    return conn.execute("SELECT pg_get_viewdef(to_regclass('sector_market_peer_runtime'), true)").fetchone()[0]


def apply(conn, runtime):
    """Record `runtime` (a PeerRuntime) and show it; returns the ledger id, or None when it is the one shown."""
    from models.peers import PeerRuntime
    from pipeline.postgres_graph_fixture import _guard
    _guard(conn)
    payload = PeerRuntime.model_validate(runtime).model_dump(mode='json')
    companies, as_of = len(payload['catalog']['companies']), payload['prices']['asOf']
    with conn.transaction():
        conn.execute(LEDGER)
        before = shown(conn)
        if before and before.get('publishedAt') == payload['publishedAt'] and before['prices']['asOf'] == as_of:
            return None
        if before:
            old = len(before['catalog']['companies'])
            if companies < SHRINK_LIMIT * old or as_of < before['prices']['asOf']:
                raise ValueError(f'Peer publication {companies} companies to {as_of} against {old} to '
                                 f"{before['prices']['asOf']}: the shown runtime stays")
        ident = conn.execute('INSERT INTO candidate_peer_runtime (payload, as_of, companies, published_at, previous_view) '
                             'VALUES (%s,%s,%s,%s,%s) RETURNING id',
                             (Jsonb(payload), as_of, companies, payload['publishedAt'], _view(conn))).fetchone()[0]
        conn.execute(sql.SQL('CREATE OR REPLACE VIEW sector_market_peer_runtime AS SELECT true AS singleton, payload '
                             'FROM candidate_peer_runtime WHERE id = {}').format(sql.Literal(ident)))
    return ident


def rollback(conn):
    """Restore the read path the latest shown row replaced; returns that row's id (None if nothing to undo)."""
    from pipeline.postgres_graph_fixture import _guard
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('candidate_peer_runtime')").fetchone()[0] is None:
            return None
        row = conn.execute('SELECT id, previous_view FROM candidate_peer_runtime WHERE rolled_back_at IS NULL '
                           'ORDER BY id DESC LIMIT 1').fetchone()
        if row is None:
            return None
        conn.execute('CREATE OR REPLACE VIEW sector_market_peer_runtime AS ' + row[1].rstrip().rstrip(';'))
        conn.execute('UPDATE candidate_peer_runtime SET rolled_back_at = now() WHERE id = %s', (row[0],))
    return row[0]
