"""Experimental sector map snapshot and reader; never registered in live API.

The caller supplies a query-only SQLite read transaction and an isolated
PostgreSQL connection. COPY streams rows without retaining the price history in
memory. PostgreSQL replacement is one transaction, so a failure rolls back.
This captures a derived membership map, not all source tables or Peer files.
"""
import uuid
import re

from pipeline.sector_overrides import effective_sectors

_LOCK_KEY = 0x534543544F524D50
_COLUMNS = ('id', 'stock_code', 'trade_date', 'open', 'high', 'low', 'close',
            'volume', 'market_cap', 'shares', 'fetched_at')


def load_sector_market(source, destination, *, peer_runtime=None, document_generation=None, include_us=False):
    if not source.in_transaction or source.execute('PRAGMA query_only').fetchone()[0] != 1:
        raise ValueError('A query-only SQLite transaction is required')
    if include_us and document_generation is None:
        raise ValueError('US sector data requires a linked document generation')
    index_columns = [row[2] for row in source.execute('PRAGMA index_info(idx_entity_links_entity)')]
    if index_columns != ['entity_id', 'link_type']:
        raise ValueError('Unsupported SQLite entity link index')
    if peer_runtime is not None:
        from models.peers import PeerRuntime
        # Revalidate even an existing model so mutations cannot bypass validation.
        value = peer_runtime.model_dump(mode='json') if isinstance(peer_runtime, PeerRuntime) else peer_runtime
        peer_runtime = PeerRuntime.model_validate(value)
        if peer_runtime.origin == 'collector' and (
            {c.code for c in peer_runtime.catalog.companies} != set(peer_runtime.prices.prices)
        ):
            raise ValueError('Peer catalog and price membership differ')
    # Mapping is small; the 1M+ price history below is never materialized.
    members = effective_sectors(source)
    count = 0
    with destination.transaction():
        database, schema = destination.execute('SELECT current_database(), current_schema()').fetchone()
        if database != 'fixture' or not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema):
            raise ValueError('Refusing sector writes outside the disposable fixture schema')
        destination.execute('SELECT pg_advisory_xact_lock(%s)', (_LOCK_KEY,))
        prior = destination.execute('SELECT linked_document_generation FROM sector_market_metadata WHERE singleton').fetchone()
        if prior and prior[0] and document_generation is None:
            raise ValueError('A linked sector snapshot must be replaced together with documents')
        destination.execute('TRUNCATE sector_market_metadata, sector_market_prices, sector_market_membership, sector_market_companies, '
                            'sector_market_groups, sector_market_peer_links, '
                            'sector_market_benchmarks, sector_market_benchmark_prices, sector_market_index, '
                            'sector_market_peer_runtime, sector_market_sector_names, '
                            'sector_market_themes, sector_market_narratives, sector_market_entities, '
                            'sector_market_company_entities, sector_market_documents, sector_market_document_links, '
                            'sector_market_doc_scan, sector_market_trade_follow, sector_market_trade_stats, '
                            'sector_market_taiwan_revenue, sector_market_season_themes, sector_market_overviews, '
                            'sector_market_us_metadata, sector_market_us_classifications, sector_market_us_prices')
        if include_us:
            count_us = 0
            with destination.cursor().copy('COPY sector_market_us_classifications (ticker,sector,industry,fetched_at) FROM STDIN') as copy:
                for row in source.execute('SELECT ticker,sector,industry,fetched_at FROM us_ticker_sectors'):
                    copy.write_row(tuple(row))
                    count_us += 1
            destination.execute('INSERT INTO sector_market_us_metadata(generation_id,classifications) VALUES (%s,%s)',
                                (document_generation, count_us))
            with destination.cursor().copy('COPY sector_market_us_prices (stock_code,trade_date,close) FROM STDIN') as copy:
                for row in source.execute('SELECT stock_code,trade_date,close FROM us_prices WHERE close IS NOT NULL'):
                    copy.write_row(tuple(row))
        with destination.cursor().copy(
            'COPY sector_market_prices (' + ', '.join(_COLUMNS) + ') FROM STDIN'
        ) as copy:
            for row in source.execute('SELECT ' + ', '.join(_COLUMNS) + ' FROM stock_prices'):
                copy.write_row(tuple(row))
                count += 1
        with destination.cursor().copy(
            'COPY sector_market_membership (stock_code, sector, ordinal) FROM STDIN'
        ) as copy:
            for ordinal, (code, sector) in enumerate(members.items()):
                copy.write_row((code, sector, ordinal))
        with destination.cursor().copy(
            'COPY sector_market_companies (ordinal, stock_code, corp_name) FROM STDIN'
        ) as copy:
            for ordinal, row in enumerate(source.execute(
                "SELECT stock_code, corp_name FROM companies WHERE stock_code IS NOT NULL AND stock_code != ''")):
                copy.write_row((ordinal, *row))
        with destination.cursor().copy('COPY sector_market_groups (sector) FROM STDIN') as copy:
            for row in source.execute('SELECT DISTINCT group_name FROM sector_map'):
                copy.write_row(tuple(row))
        with destination.cursor().copy('''COPY sector_market_peer_links
            (sector, peer_group_id, sort, partial, note, source) FROM STDIN''') as copy:
            for row in source.execute('''SELECT sector, peer_group_id, sort, partial, note, source
                                          FROM sector_peer_map'''):
                copy.write_row(tuple(row))
        for target, columns, table in (
            ('sector_market_benchmarks', 'sector, ticker, name, tracks, note', 'sector_benchmarks'),
            ('sector_market_benchmark_prices', 'ticker, trade_date, close', 'sector_benchmark_prices'),
            ('sector_market_index', 'sector, trade_date, value', 'sector_index'),
            ('sector_market_sector_names', 'sector_name, group_name', 'sector_map'),
            ('sector_market_themes', 'group_name, themes_json', 'value_chains'),
            ('sector_market_entities', 'id, type, name, status', 'entities'),
            ('sector_market_documents', 'id, source_type, source_id, title, published_at', 'raw_documents'),
            ('sector_market_document_links', 'id, doc_id, entity_id, link_type', 'entity_links'),
            ('sector_market_trade_stats', 'id, hs_code, period, export_usd', 'trade_stats'),
            ('sector_market_taiwan_revenue', 'code, ym, yoy_pct', 'tw_monthly_revenue'),
            ('sector_market_season_themes', 'id, season, sector, verdict, body_json', 'season_themes'),
            ('sector_market_overviews', 'sector, question, bullets_json, narrative_ids, model, generated_at', 'sector_overviews'),
        ):
            with destination.cursor().copy(f'COPY {target} ({columns}) FROM STDIN') as copy:
                for row in source.execute(f'SELECT {columns} FROM {table}'):
                    copy.write_row(tuple(row))
        with destination.cursor().copy('''COPY sector_market_narratives
            (ordinal, id, topic, title, core_question, doc_count, created_at) FROM STDIN''') as copy:
            for ordinal, row in enumerate(source.execute('''SELECT id, topic, title, core_question, doc_count,
                created_at FROM narratives WHERE superseded_at IS NULL ORDER BY created_at DESC''')):
                copy.write_row((ordinal, *row))
        with destination.cursor().copy('''COPY sector_market_trade_follow
            (ordinal, hs_code, item_name, group_label, active) FROM STDIN''') as copy:
            for ordinal, row in enumerate(source.execute('SELECT hs_code, item_name, group_label, active FROM trade_follow')):
                copy.write_row((ordinal, *row))
        with destination.cursor().copy('COPY sector_market_company_entities (entity_id, stock_code) FROM STDIN') as copy:
            for row in source.execute('''SELECT e.id, c.stock_code FROM entities e JOIN companies c
                ON c.corp_code = json_extract(e.meta_json, '$.corp_code')
                WHERE e.type = 'company' AND c.stock_code IS NOT NULL'''):
                copy.write_row(tuple(row))
        with destination.cursor().copy('COPY sector_market_doc_scan (id_count, document_first) FROM STDIN') as copy:
            for n in range(1, 201):
                q = ("EXPLAIN QUERY PLAN SELECT el.doc_id, el.entity_id, d.source_type, d.title, d.published_at "
                     "FROM entity_links el JOIN raw_documents d ON d.id = el.doc_id WHERE el.entity_id IN ("
                     + ','.join('?' * n) + ") AND d.published_at >= ? AND d.source_type IN (?,?,?,?)")
                plan = [r[3] for r in source.execute(q, [*([0] * n), '2000-01-01', 'blog', 'scrap', 'web', 'youtube'])]
                doc_first = (len(plan) == 2 and 'sqlite_autoindex_raw_documents_1' in plan[0]
                             and 'sqlite_autoindex_entity_links_1' in plan[1])
                link_first = (len(plan) == 2 and 'idx_entity_links_entity' in plan[0]
                              and 'INTEGER PRIMARY KEY' in plan[1])
                if not (doc_first or link_first):
                    raise ValueError('Unsupported SQLite document scan plan')
                copy.write_row((n, doc_first))
        if peer_runtime is not None:
            from psycopg.types.json import Jsonb
            destination.execute('INSERT INTO sector_market_peer_runtime (payload) VALUES (%s)',
                                (Jsonb(peer_runtime.model_dump(mode='json')),))
        destination.execute('INSERT INTO sector_market_metadata (generation_id, linked_document_generation) '
                            'VALUES (%s, %s)', (document_generation or uuid.uuid4(), document_generation is not None))
    return {'prices': count, 'members': len(members)}


class PostgreSQLSectorSource:
    """Use one caller-owned REPEATABLE READ transaction for every map lookup."""

    def __init__(self, conn):
        self.conn = conn

    def generation(self):
        row = self.conn.execute('SELECT generation_id, linked_document_generation '
                                'FROM sector_market_metadata WHERE singleton').fetchone()
        if not row:
            raise ValueError('Sector snapshot is missing')
        if row[1]:
            current = self.conn.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
            if not current or current[0] != row[0]:
                raise ValueError('Sector and document snapshots are not aligned')
        return row

    def latest_date(self):
        return self.conn.execute('SELECT max(trade_date) FROM sector_market_prices').fetchone()[0]

    def members(self):
        return dict(self.conn.execute('SELECT stock_code, sector FROM sector_market_membership ORDER BY ordinal'))

    def previous_date(self, before):
        return self.conn.execute('SELECT max(trade_date) FROM sector_market_prices WHERE trade_date < %s',
                                 (before,)).fetchone()[0]

    def company_names(self, codes):
        if not codes:
            return {}
        return dict(self.conn.execute('SELECT stock_code, corp_name FROM sector_market_companies '
                                      'WHERE stock_code = ANY(%s) ORDER BY ordinal', (codes,)))

    def trade_items(self, groups):
        return list(self.conn.execute('SELECT hs_code, item_name, group_label FROM sector_market_trade_follow '
                                      'WHERE active = 1 AND group_label = ANY(%s) ORDER BY ordinal', (groups,)))

    def latest_trade_period(self):
        return self.conn.execute('SELECT max(period) FROM sector_market_trade_stats').fetchone()[0]

    def trade_export(self, code, period):
        row = self.conn.execute('SELECT export_usd FROM sector_market_trade_stats '
                                'WHERE hs_code = %s AND period = %s ORDER BY id LIMIT 1', (code, period)).fetchone()
        return row[0] if row else None

    def taiwan_yoys(self, codes):
        ym = self.conn.execute('SELECT max(ym) FROM sector_market_taiwan_revenue').fetchone()[0]
        rows = self.conn.execute('SELECT yoy_pct FROM sector_market_taiwan_revenue '
                                 'WHERE ym = %s AND yoy_pct IS NOT NULL AND code = ANY(%s)', (ym, codes)) if ym and codes else []
        return ym, [r[0] for r in rows]

    def season_themes(self, keys):
        season = self.conn.execute('SELECT max(season) FROM sector_market_season_themes WHERE sector = ANY(%s)', (keys,)).fetchone()[0]
        rows = {r[0]: {'sector': r[0], 'verdict': r[1], 'body_json': r[2]} for r in self.conn.execute(
            'SELECT sector, verdict, body_json FROM sector_market_season_themes '
            'WHERE season = %s AND sector = ANY(%s) ORDER BY id', (season, keys))} if season else {}
        return season, rows

    def sector_names(self):
        return list(self.conn.execute('SELECT sector_name, group_name FROM sector_market_sector_names'))

    def sector_themes(self):
        return list(self.conn.execute('SELECT group_name, themes_json FROM sector_market_themes'))

    def active_narratives(self):
        columns = ('id', 'topic', 'title', 'core_question', 'doc_count', 'created_at')
        return [dict(zip(columns, row)) for row in self.conn.execute(
            'SELECT id, topic, title, core_question, doc_count, created_at '
            'FROM sector_market_narratives ORDER BY ordinal')]

    def sector_entity(self, sector):
        for part in sector.split('·'):
            row = self.conn.execute("SELECT id, name FROM sector_market_entities WHERE type='sector' "
                                    "AND name=%s AND status='active' ORDER BY id LIMIT 1", (part,)).fetchone()
            if row:
                return {'feed_industry': row[1], 'entity_id': row[0]}
        return {'feed_industry': None, 'entity_id': None}

    def overview(self, sector):
        import json
        row = self.conn.execute('SELECT question, bullets_json, narrative_ids, model, generated_at '
                                'FROM sector_market_overviews WHERE sector = %s', (sector,)).fetchone()
        if not row:
            return None
        question, bullets, ids, model, generated = row
        return {'question': question, 'bullets': json.loads(bullets), 'model': model,
                'generated_at': generated, 'narrative_ids': [int(x) for x in (ids or '').split(',') if x]}

    def topic_entity_ids(self, keywords):
        return [r[0] for r in self.conn.execute("SELECT id FROM sector_market_entities "
                "WHERE type IN ('sector', 'theme') AND name = ANY(%s)", (sorted(keywords),))]

    def stock_entity_ids(self, codes):
        return [r[0] for r in self.conn.execute('SELECT entity_id FROM sector_market_company_entities '
                                                'WHERE stock_code = ANY(%s)', (codes,))]

    def document_links(self, entity_ids, since, types):
        policy = self.conn.execute('SELECT document_first FROM sector_market_doc_scan WHERE id_count=%s',
                                   (len(entity_ids),)).fetchone()
        if policy is None:
            raise ValueError('Document scan size not captured')
        order = ('d.source_type COLLATE "C", d.source_id COLLATE "C" NULLS FIRST, d.id, '
                 'el.entity_id, el.link_type COLLATE "C" NULLS FIRST, el.id') if policy[0] else (
                     'el.entity_id, el.link_type COLLATE "C" NULLS FIRST, el.id')
        return list(self.conn.execute('''SELECT el.doc_id, el.entity_id, d.source_type, d.title, d.published_at
            FROM sector_market_document_links el JOIN sector_market_documents d ON d.id = el.doc_id
            WHERE el.entity_id = ANY(%s) AND d.published_at >= %s AND d.source_type = ANY(%s)
            ORDER BY ''' + order, (entity_ids, since, list(types))))

    def peer_runtime(self):
        """Return the bundle committed with this snapshot, or None if absent."""
        from models.peers import PeerRuntime
        row = self.conn.execute('SELECT payload FROM sector_market_peer_runtime WHERE singleton').fetchone()
        if not row:
            return None
        # The legacy API (routers.peers.read_runtime) computes the ages per request, not at publication.
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now, prices = datetime.now(ZoneInfo('Asia/Seoul')), row[0]['prices']
        return PeerRuntime.model_validate({
            **row[0], 'priceAgeDays': max(0, (now.date() - datetime.fromisoformat(prices['asOf']).date()).days),
            'snapshotAgeHours': max(0, (now - datetime.fromisoformat(prices['collectedAt'])).total_seconds() / 3600)})

    def benchmarks(self):
        return {sector: {'ticker': ticker, 'name': name, 'tracks': tracks, 'note': note,
                         'kind': 'etf' if ticker else 'computed'}
                for sector, ticker, name, tracks, note in self.conn.execute(
                    'SELECT sector, ticker, name, tracks, note FROM sector_market_benchmarks')}

    def benchmark_series(self, sector, bench):
        if bench and bench.get('ticker'):
            return list(self.conn.execute('SELECT trade_date, close FROM sector_market_benchmark_prices '
                                          'WHERE ticker = %s ORDER BY trade_date', (bench['ticker'],)))
        return list(self.conn.execute('SELECT trade_date, value FROM sector_market_index '
                                      'WHERE sector = %s ORDER BY trade_date', (sector,)))

    def kospi_series(self):
        from pipeline.sector_benchmarks import KOSPI
        return list(self.conn.execute('SELECT trade_date, close FROM sector_market_benchmark_prices '
                                      'WHERE ticker = %s ORDER BY trade_date', (KOSPI,)))

    def sector_peers(self, runtime):
        """Combine same-transaction DB rows with the caller's validated Peer bundle."""
        from pipeline.sector_peers import AUTO_SHARE, build
        sectors = sorted(row[0] for row in self.conn.execute('SELECT sector FROM sector_market_groups'))
        rows = [dict(zip(('sector', 'peer_group_id', 'sort', 'partial', 'note', 'source'), row))
                for row in self.conn.execute('SELECT sector, peer_group_id, sort, partial, note, source '
                                             'FROM sector_market_peer_links')]
        groups = [{'id': g.id, 'name': g.name, 'scope': g.scope} for g in runtime.catalog.groups]
        members = {}
        for company in runtime.catalog.companies:
            for group in company.groupIds:
                members.setdefault(group, []).append(company.code)
        return {'catalog_as_of': str(runtime.catalog.asOf), 'auto_share': AUTO_SHARE,
                'sectors': build(sectors, rows, groups, members, self.members())}

    def snapshot(self, as_of):
        rows = self.conn.execute('''
            WITH RECURSIVE codes(stock_code) AS (
                (SELECT stock_code FROM sector_market_prices
                 WHERE close IS NOT NULL
                 ORDER BY stock_code COLLATE "C" LIMIT 1)
                UNION ALL
                SELECT next_code.stock_code FROM codes
                CROSS JOIN LATERAL (
                    SELECT stock_code FROM sector_market_prices
                    WHERE close IS NOT NULL
                      AND stock_code COLLATE "C" > codes.stock_code COLLATE "C"
                    ORDER BY stock_code COLLATE "C" LIMIT 1
                ) next_code
            )
            SELECT codes.stock_code, price.close, price.market_cap
            FROM codes CROSS JOIN LATERAL (
                SELECT close, market_cap FROM sector_market_prices
                WHERE stock_code COLLATE "C" = codes.stock_code COLLATE "C"
                  AND trade_date <= %s AND close IS NOT NULL
                ORDER BY trade_date DESC LIMIT 1
            ) price
        ''', (as_of,))
        return {code: (close, market_cap or 0) for code, close, market_cap in rows}


def attach_peer_runtime(target, peer_runtime):
    """Add a separately captured Peer bundle beside a base snapshot that has none."""
    from psycopg.types.json import Jsonb
    from models.peers import PeerRuntime
    from pipeline.postgres_graph_fixture import _guard
    _guard(target)
    payload = PeerRuntime.model_validate(peer_runtime).model_dump(mode='json')
    with target.transaction():
        if target.execute("SELECT to_regclass('sector_market_peer_runtime_overlay')").fetchone()[0] is not None:
            raise ValueError('Peer runtime overlay already attached')
        if target.execute('SELECT 1 FROM sector_market_peer_runtime').fetchone():
            raise ValueError('Snapshot already has a Peer runtime')
        definition = target.execute("SELECT pg_get_viewdef(to_regclass('sector_market_peer_runtime'),true)").fetchone()[0]
        if definition is None or 'WHERE false' not in definition:
            raise ValueError('Unexpected Peer runtime view')
        target.execute('CREATE TABLE sector_market_peer_runtime_overlay (singleton BOOLEAN PRIMARY KEY DEFAULT true '
                       'CHECK(singleton),payload JSONB NOT NULL)')
        target.execute('INSERT INTO sector_market_peer_runtime_overlay (payload) VALUES (%s)', (Jsonb(payload),))
        target.execute(f'CREATE OR REPLACE VIEW sector_market_peer_runtime AS {definition.rstrip().rstrip(";")} '
                       'UNION ALL SELECT singleton,payload FROM sector_market_peer_runtime_overlay')
