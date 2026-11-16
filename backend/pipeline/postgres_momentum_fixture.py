"""Read saved call momentum from a single disposable snapshot."""
from pipeline import call_momentum
from pipeline.postgres_signals_fixture import _guard_read
from pipeline.postgres_urgent_selection_fixture import open_snapshot


def momentum(conn):
    _guard_read(conn)
    db, _, _ = open_snapshot(conn, ('call_momentum', 'call_extracts', 'transcript_follow',
                                   'earnings_releases', 'transcripts'))
    try:
        db.execute('PRAGMA query_only=ON')
        as_of = db.execute('SELECT max(computed_at) FROM call_momentum').fetchone()[0]
        return {**call_momentum.by_season(db), 'coverage': call_momentum.coverage(db),
                'as_of': as_of, 'sec_configured': False}
    finally:
        db.close()
