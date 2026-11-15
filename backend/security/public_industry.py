"""Readonly public ETF map input, excluding all personal follow/document data."""
from pathlib import Path
import sqlite3

from config import DB_PATH


def _authorize(action, first, second, database, source):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if (action == sqlite3.SQLITE_READ and database == 'main'
            and first == 'sector_benchmark_prices'
            and second in {'ticker', 'trade_date', 'close'}):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _connection(path, authorize, *, snapshot=False) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path or DB_PATH).resolve().as_uri() + '?mode=ro', uri=True, timeout=3)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        if snapshot:
            conn.execute('BEGIN')
        conn.set_authorizer(authorize)
        return conn
    except Exception:
        conn.close()
        raise


def industry_connection(path: Path | None = None) -> sqlite3.Connection:
    return _connection(path, _authorize)


KR_COLUMNS = {
    'stock_prices': {'id', 'stock_code', 'trade_date', 'close', 'market_cap'},
    'companies': {'stock_code', 'sector', 'corp_name'},
    'entities': {'id', 'type', 'aliases', 'name'},
    'entity_relations': {'src_id', 'dst_id', 'rel_type'},
    'sector_map': {'sector_name', 'group_name'},
    'sector_overrides': {'stock_code', 'sector'},
    'sector_benchmark_prices': {'ticker', 'trade_date', 'close'},
    'sector_index': {'sector', 'trade_date', 'value'},
}


def _authorize_kr(action, first, second, database, source):
    if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE}:
        return sqlite3.SQLITE_OK
    if (action == sqlite3.SQLITE_READ and database == 'main'
            and first in KR_COLUMNS and second in KR_COLUMNS[first]):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and second in {'min', 'max'}:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def kr_industry_connection(path: Path | None = None) -> sqlite3.Connection:
    return _connection(path, _authorize_kr, snapshot=True)


def kr_industry_map(conn):
    from pipeline.sector_benchmarks import SEED
    from pipeline.sector_rs import sector_map_from_connection, snapshot_memo
    from pipeline.sector_view import industry_map
    # Names/descriptions are reviewed code metadata, not arbitrary DB text.
    benches = {sector: dict(ticker=ticker, name=name, tracks=tracks, note=note)
               for sector, ticker, name, tracks, note in SEED}
    with snapshot_memo():
        rs = sector_map_from_connection(conn, allowed_groups=set(benches))
        return industry_map(conn, rs=rs, benchmark_map=benches)


def kr_sector_market(conn, sector):
    from pipeline.sector_benchmarks import SEED
    from pipeline.sector_rs import sector_map_from_connection, group_members_from_connection, snapshot_memo
    from pipeline.sector_view import bench_series, bench_out, quote, kospi_series, _members
    benches = {name: dict(ticker=ticker, name=label, tracks=tracks, note=note)
               for name, ticker, label, tracks, note in SEED}
    if sector not in benches:
        return None
    with snapshot_memo():
        rs = sector_map_from_connection(conn, allowed_groups=set(benches))
        group = next((g for g in rs['groups'] if g['name'] == sector), None)
        if group is None:
            return None
        series = bench_series(conn, sector, benches[sector])
        kospi = dict(kospi_series(conn))
        rows = group_members_from_connection(conn, sector, limit=100000)['items']
        members = _members(conn, sector, rs['as_of'], member_rows=rows)
        return {**group, 'as_of':rs['as_of'], 'benchmark':bench_out(benches[sector]), **quote(series),
                'series':[{'d':d, 'v':v, 'k':kospi.get(d)} for d,v in series],
                'constituents':members, 'top_weights':members[:8]}
