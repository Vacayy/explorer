"""Historical market calculations over prepared prices, without personal era inputs."""
from contextlib import closing
from datetime import date
import math

from pipeline import regimes
from security.public_us_season import connection


def _prices(conn, ticker):
    series = [(r[0], r[1]) for r in conn.execute(
        'SELECT trade_date,close FROM us_prices WHERE stock_code=? ORDER BY trade_date', (ticker,))]
    for day, value in series:
        date.fromisoformat(day)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('Invalid prepared price')
    return series


def _recessions(conn):
    rows = conn.execute('SELECT snapshot_date,value FROM public_regime_recessions ORDER BY snapshot_date').fetchall()
    for day, value in rows:
        date.fromisoformat(day)
        if value not in (0, 1):
            raise ValueError('Invalid prepared recession observation')
    return regimes.recessions_from_rows(rows)


def stored_regimes(*, path=None):
    with closing(connection(path)) as conn:
        return regimes.regimes_from_series(_prices(conn, regimes.INDEX), _recessions(conn))


def stored_brk(bench='sp500tr', span='all', *, path=None):
    meta = regimes.BENCHES[bench]
    with closing(connection(path)) as conn:
        # Validate the two splice inputs before reusing the original BRK-A/B logic.
        _prices(conn, regimes.BRK_A)
        _prices(conn, regimes.BRK_B)
        return regimes.brk_from_series(regimes._brk(conn), _prices(conn, meta['ticker']),
            _prices(conn, regimes.INDEX), _recessions(conn), bench=bench, span=span)
