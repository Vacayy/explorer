"""Sector market tables kept current from the collected data (architect #3 6942419202, PM 6942386104).

The sector map, sector details, peers, US industry screens and the portfolio's price history read the
sector_market_* tables, which only the base snapshot loader wrote (frozen at the base date). A refresh loads them
again with the unchanged loader (postgres_sector_market.load_sector_market, the base build's options: US data,
the linked document generation) from the projection SQLite (base + collected rows), into a NEW store schema; checks
it against the tables the candidate reads now (no table below half its rows, the latest price dates may not go back);
then points the candidate's sector_market_* views at the new store in one transaction and drops the previous store.
The base schema is never written: rolling back is pointing the views at it again (`repoint(conn, base)`).
"""
import re
import uuid
from pathlib import Path

from psycopg import sql

# The loader's tables, without the peer runtime (its candidate view carries the peer bundle overlay; untouched).
TABLES = ('sector_market_metadata', 'sector_market_prices', 'sector_market_membership', 'sector_market_companies',
          'sector_market_groups', 'sector_market_peer_links', 'sector_market_benchmarks', 'sector_market_benchmark_prices',
          'sector_market_index', 'sector_market_sector_names', 'sector_market_themes', 'sector_market_narratives',
          'sector_market_entities', 'sector_market_company_entities', 'sector_market_documents',
          'sector_market_document_links', 'sector_market_doc_scan', 'sector_market_trade_follow',
          'sector_market_trade_stats', 'sector_market_taiwan_revenue', 'sector_market_season_themes',
          'sector_market_overviews', 'sector_market_us_metadata', 'sector_market_us_classifications',
          'sector_market_us_prices')
DATED = {'sector_market_prices': 'trade_date', 'sector_market_us_prices': 'trade_date',
         'sector_market_benchmark_prices': 'trade_date', 'sector_market_index': 'trade_date'}
SHRINK_LIMIT = 0.5
DDL = Path(__file__).resolve().parents[1] / 'refactor_sql/sector_market.sql'


def _measure(conn, schema):
    out = {}
    for table in TABLES:
        name = sql.Identifier(schema, table) if schema else sql.Identifier(table)
        count = conn.execute(sql.SQL('SELECT count(*) FROM {}').format(name)).fetchone()[0]
        latest = conn.execute(sql.SQL('SELECT max({}) FROM {}').format(sql.Identifier(DATED[table]), name)).fetchone()[0] \
            if table in DATED else None
        out[table] = (count, str(latest) if latest is not None else None)
    return out


def current_store(conn):
    """The schema the candidate's sector views read now."""
    definition = conn.execute("SELECT view_definition FROM information_schema.views WHERE table_schema=current_schema() "
                              "AND table_name='sector_market_prices'").fetchone()[0]
    return re.search(r'(refactor_fixture_[0-9a-f]{32})\.sector_market_prices', definition).group(1)


def base_schema(conn):
    """The base snapshot: what the never-repointed peer runtime view still reads."""
    definition = conn.execute("SELECT view_definition FROM information_schema.views WHERE table_schema=current_schema() "
                              "AND table_name='sector_market_peer_runtime'").fetchone()[0]
    return re.search(r'(refactor_fixture_[0-9a-f]{32})\.sector_market_peer_runtime', definition).group(1)


def repoint(conn, store):
    """Point every refreshed sector view at `store` (same columns: CREATE OR REPLACE refuses a different shape)."""
    for table in TABLES:
        conn.execute(sql.SQL('CREATE OR REPLACE VIEW {view} AS SELECT * FROM {src} UNION ALL SELECT * FROM {src} WHERE FALSE')
                     .format(view=sql.Identifier(table), src=sql.Identifier(store, table)))


def refresh(admin, candidate_factory, store_factory_for, projection_path, *, base, drop_previous=True):
    """Load a new store from the projection, check it, switch the views; returns the measurements and timings."""
    import sqlite3
    import time
    from pipeline.postgres_sector_market import load_sector_market
    started = time.monotonic()
    store = 'refactor_fixture_' + uuid.uuid4().hex
    admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(store)))
    try:
        with store_factory_for(store) as conn:
            conn.execute(DDL.read_text())
            conn.commit()
        with candidate_factory() as candidate:
            # The base build linked the sector snapshot to the document generation (snapshot_metadata).
            generation = candidate.execute('SELECT generation_id FROM snapshot_metadata').fetchone()[0]
            before, previous = _measure(candidate, None), current_store(candidate)
        source = sqlite3.connect(f'file:{projection_path}?mode=ro', uri=True)
        source.row_factory = sqlite3.Row
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        try:
            with store_factory_for(store) as conn:
                load_sector_market(source, conn, document_generation=generation, include_us=True)
        finally:
            source.close()
        loaded = time.monotonic()
        with store_factory_for(store) as conn:
            after = _measure(conn, store)
        # The collected-table guard (half of what is read now), and the latest dates may not move back. A small drop
        # is legitimate: the candidate's own link decisions (keyword removals) are in the projection, not the base.
        shrunk = {t: (before[t], after[t]) for t in TABLES if after[t][0] < SHRINK_LIMIT * before[t][0]
                  or (before[t][1] and (after[t][1] or '') < before[t][1])}
        if shrunk:
            raise ValueError(f'Refresh would shrink or move back: {sorted(shrunk)}')
        with candidate_factory() as candidate, candidate.transaction():
            repoint(candidate, store)
        # The base is the rollback point and stays; a cloned schema (a rehearsal) shares its source's store: kept.
        if drop_previous and previous != base:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(previous)))
        return {'store': store, 'previous': previous, 'before': before, 'after': after,
                'load_seconds': round(loaded - started, 1), 'total_seconds': round(time.monotonic() - started, 1)}
    except BaseException:
        admin.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(store)))
        raise
