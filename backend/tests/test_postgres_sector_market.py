"""Compare an isolated PostgreSQL sector snapshot with its SQLite source."""
import os
import sqlite3
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import psycopg
from psycopg import sql

from pipeline.postgres_sector_market import PostgreSQLSectorSource, load_sector_market
from pipeline.sector_rs import SQLiteSectorSource, build_sector_map, group_members_from_source
from pipeline.sector_peers import sector_peers
from pipeline.sector_view import (industry_map, industry_map_from_source, sector_members_from_source,
                                  sector_docs, sector_docs_from_source, sector_narratives, sector_narratives_from_source,
                                  sector_peer_list, sector_peer_list_from_source)


@unittest.skipUnless(os.getenv('REFACTOR_TEST_DISPOSABLE') == '1', 'disposable fixture required')
class SectorMarketTest(unittest.TestCase):
    def setUp(self):
        dsn = os.environ['REFACTOR_POSTGRES_DSN']
        parts = psycopg.conninfo.conninfo_to_dict(dsn)
        if (parts.get('host'), parts.get('dbname'), parts.get('user')) != ('pg', 'fixture', 'fixture'):
            raise RuntimeError('Refusing non-fixture PostgreSQL')
        self.dsn = dsn
        self.schema = 'refactor_fixture_' + uuid.uuid4().hex
        with psycopg.connect(dsn) as c:
            c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.pg = psycopg.connect(dsn, options=f'-c search_path={self.schema}', autocommit=True)
        self.pg.execute((Path(__file__).resolve().parents[1] / 'refactor_sql/sector_market.sql').read_text())
        self.db = sqlite3.connect(':memory:')
        self.db.executescript('''
            CREATE TABLE stock_prices(id INTEGER PRIMARY KEY, stock_code TEXT NOT NULL,
                trade_date TEXT NOT NULL, open INTEGER, high INTEGER, low INTEGER,
                close INTEGER, volume INTEGER, market_cap INTEGER, shares INTEGER, fetched_at TEXT,
                UNIQUE(stock_code, trade_date));
            CREATE TABLE companies(stock_code TEXT, sector TEXT, corp_name TEXT, corp_code TEXT);
            CREATE TABLE sector_map(sector_name TEXT, group_name TEXT);
            CREATE TABLE sector_overrides(stock_code TEXT, sector TEXT);
            CREATE TABLE sector_peer_map(sector TEXT, peer_group_id TEXT, sort INTEGER,
                                         partial INTEGER, note TEXT, source TEXT);
            CREATE TABLE sector_benchmarks(sector TEXT, ticker TEXT, name TEXT, tracks TEXT, note TEXT);
            CREATE TABLE sector_benchmark_prices(ticker TEXT, trade_date TEXT, close REAL);
            CREATE TABLE sector_index(sector TEXT, trade_date TEXT, value REAL);
            CREATE TABLE value_chains(group_name TEXT, themes_json TEXT);
            CREATE TABLE narratives(id INTEGER, topic TEXT, title TEXT, core_question TEXT,
                                    doc_count INTEGER, created_at TEXT, superseded_at TEXT);
            CREATE TABLE entities(id INTEGER, type TEXT, aliases TEXT, name TEXT, status TEXT, meta_json TEXT);
            CREATE TABLE entity_relations(src_id INTEGER, dst_id INTEGER, rel_type TEXT);
            CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, source_type TEXT, source_id TEXT, title TEXT, published_at TEXT,
                                       UNIQUE(source_type,source_id));
            CREATE TABLE entity_links(id INTEGER PRIMARY KEY, doc_id INTEGER, entity_id INTEGER, link_type TEXT,
                                      UNIQUE(doc_id,entity_id,link_type));
            CREATE INDEX idx_entity_links_entity ON entity_links(entity_id);
            INSERT INTO sector_map VALUES ('source-a','A'),('source-b','B');
            INSERT INTO companies VALUES ('001','source-a','one','c1'),('002','source-b','two','c2'),('003','source-a','three','c3');
            INSERT INTO sector_overrides VALUES ('003','B');
            INSERT INTO sector_peer_map VALUES ('A','g',0,0,NULL,'seed');
            INSERT INTO sector_benchmarks VALUES ('A','AAA','ETF A','index',NULL),('B',NULL,NULL,NULL,NULL);
            INSERT INTO sector_benchmark_prices VALUES ('AAA','2026-01-09',10.0),('^KS11','2026-01-09',100.0);
            INSERT INTO sector_index VALUES ('B','2026-01-09',120.0);
            INSERT INTO value_chains VALUES ('A','["theme-a"]');
            INSERT INTO narratives VALUES (1,'theme-a','title',NULL,2,'2026-01-09',NULL);
            INSERT INTO entities VALUES (1,'theme',NULL,'theme-a','active',NULL);
            INSERT INTO entities VALUES (2,'company',NULL,'one','active','{"corp_code":"c1"}');
            INSERT INTO raw_documents VALUES (1,'blog','b1','theme-a report','2026-01-09');
            INSERT INTO entity_links VALUES (1,1,1,'sector'),(2,1,2,'stock');
            INSERT INTO stock_prices(stock_code,trade_date,close,market_cap) VALUES
                ('001','2025-10-01',100,900),('002','2025-10-01',100,600),
                ('003','2025-10-01',200,100),('001','2026-01-02',150,900),
                ('002','2026-01-02',120,600),('003','2026-01-02',220,NULL),
                ('001','2026-01-09',160,1000),('002','2026-01-09',110,700),
                ('003','2026-01-09',NULL,200);
        ''')
        self.db.execute('PRAGMA query_only=ON')
        self.db.execute('BEGIN')

    def tearDown(self):
        self.db.close()
        self.pg.close()
        with psycopg.connect(self.dsn) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def test_map_and_failed_replacement(self):
        bundle = {
            'catalog': {'version': 'test', 'asOf': '2026-01-09', 'groups': [], 'companies': []},
            'prices': {'version': 'test', 'asOf': '2026-01-09', 'collectedAt': '2026-01-09T00:00:00Z',
                       'sourceUrl': 'https://example.com', 'sourceHash': 'a' * 64,
                       'field': 'regularMarketClosingPrice', 'session': 'KRX_REGULAR',
                       'adjustmentStatus': 'unverified', 'dates': ['2026-01-09'], 'prices': {},
                       'qualityIssues': [], 'caveats': []},
            'origin': 'collector', 'publishedAt': '2026-01-09T00:00:00Z', 'baselineOn': None,
            'lastAttempt': None, 'priceAgeDays': 0, 'snapshotAgeHours': 0,
            'signalStatus': 'held', 'signalHoldReason': 'fixture',
        }
        result = load_sector_market(self.db, self.pg, peer_runtime=bundle)
        self.assertEqual(result, {'prices': 9, 'members': 3})
        expected = build_sector_map(SQLiteSectorSource(self.db))
        with self.pg.transaction():
            self.pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            pgsource = PostgreSQLSectorSource(self.pg)
            self.assertEqual(pgsource.peer_runtime().catalog.version, 'test')
            self.assertEqual(pgsource.snapshot('2026-01-09'), SQLiteSectorSource(self.db).snapshot('2026-01-09'))
            self.assertEqual(build_sector_map(pgsource), expected)
            self.assertEqual(group_members_from_source(pgsource, 'A'),
                             group_members_from_source(SQLiteSectorSource(self.db), 'A'))
            self.assertEqual(sector_members_from_source(pgsource, 'A', '2026-01-09'),
                             sector_members_from_source(SQLiteSectorSource(self.db), 'A', '2026-01-09'))
            self.db.row_factory = sqlite3.Row
            self.assertEqual(sector_narratives_from_source(pgsource, 'A'), sector_narratives(self.db, 'A'))
            self.assertEqual(sector_docs_from_source(pgsource, 'A', ['001'], '2026-01-09'),
                             sector_docs(self.db, 'A', ['001'], '2026-01-09'))
            prices = SimpleNamespace(asOf='2026-01-09', model_dump=lambda **_: {
                'dates': [], 'prices': {}, 'asOf': '2026-01-09', 'qualityIssues': []})
            runtime = SimpleNamespace(catalog=SimpleNamespace(
                asOf='2026-01-09', groups=[SimpleNamespace(id='g', name='그룹', scope='product')],
                companies=[SimpleNamespace(code='001', groupIds=['g'])]), prices=prices)
            self.db.row_factory = sqlite3.Row
            self.assertEqual(pgsource.sector_peers(runtime), sector_peers(self.db, runtime))
            self.assertEqual(sector_peer_list_from_source(pgsource, 'A', runtime),
                             sector_peer_list(self.db, 'A', runtime))
            self.assertIsNone(sector_peer_list_from_source(pgsource, 'missing', runtime))
            with patch('pipeline.sector_rs.compute_sector_map', return_value=expected):
                self.assertEqual(industry_map_from_source(pgsource, runtime), industry_map(self.db, runtime))
        self.pg.execute('''CREATE FUNCTION reject_price() RETURNS trigger LANGUAGE plpgsql AS $$
                        BEGIN RAISE EXCEPTION 'fixture failure'; END $$''')
        self.pg.execute('CREATE TRIGGER reject_price BEFORE INSERT ON sector_market_prices '
                        'FOR EACH ROW EXECUTE FUNCTION reject_price()')
        with self.assertRaises(psycopg.errors.RaiseException):
            load_sector_market(self.db, self.pg, peer_runtime=bundle)
        self.assertEqual(self.pg.execute('SELECT count(*) FROM sector_market_prices').fetchone()[0], 9)
        self.assertEqual(self.pg.execute('SELECT count(*) FROM sector_market_membership').fetchone()[0], 3)
        self.assertEqual(PostgreSQLSectorSource(self.pg).peer_runtime().catalog.version, 'test')


if __name__ == '__main__':
    unittest.main()
