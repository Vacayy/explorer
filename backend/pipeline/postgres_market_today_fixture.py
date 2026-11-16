"""Read saved market sessions from a disposable captured snapshot."""
from pipeline.market_today import read
from pipeline.postgres_signals_fixture import _guard_read
from pipeline.postgres_urgent_selection_fixture import open_snapshot


def market_today(conn, *, day=None, slot=None):
    _guard_read(conn)
    db,_,_=open_snapshot(conn,('market_today','market_today_links','narratives'))
    try:
        db.execute('PRAGMA query_only=ON')
        return read(day,slot,connection=db)
    finally:
        db.close()
