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
from pipeline.sector_rs import SQLiteSectorSource, build_sector_map
from pipeline.sector_peers import sector_peers
from pipeline.sector_view import industry_map, industry_map_from_source, sector_peer_list, sector_peer_list_from_source


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
            CREATE TABLE companies(stock_code TEXT, sector TEXT);
            CREATE TABLE sector_map(sector_name TEXT, group_name TEXT);
            CREATE TABLE sector_overrides(stock_code TEXT, sector TEXT);
            CREATE TABLE sector_peer_map(sector TEXT, peer_group_id TEXT, sort INTEGER,
                                         partial INTEGER, note TEXT, source TEXT);
            CREATE TABLE sector_benchmarks(sector TEXT, ticker TEXT, name TEXT, tracks TEXT, note TEXT);
            CREATE TABLE sector_benchmark_prices(ticker TEXT, trade_date TEXT, close REAL);
            CREATE TABLE sector_index(sector TEXT, trade_date TEXT, value REAL);
            CREATE TABLE entities(id INTEGER, type TEXT, aliases TEXT, name TEXT);
            CREATE TABLE entity_relations(src_id INTEGER, dst_id INTEGER, rel_type TEXT);
            INSERT INTO sector_map VALUES ('source-a','A'),('source-b','B');
            INSERT INTO companies VALUES ('001','source-a'),('002','source-b'),('003','source-a');
            INSERT INTO sector_overrides VALUES ('003','B');
            INSERT INTO sector_peer_map VALUES ('A','g',0,0,NULL,'seed');
            INSERT INTO sector_benchmarks VALUES ('A','AAA','ETF A','index',NULL),('B',NULL,NULL,NULL,NULL);
            INSERT INTO sector_benchmark_prices VALUES ('AAA','2026-01-09',10.0),('^KS11','2026-01-09',100.0);
            INSERT INTO sector_index VALUES ('B','2026-01-09',120.0);
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
        result = load_sector_market(self.db, self.pg)
        self.assertEqual(result, {'prices': 9, 'members': 3})
        expected = build_sector_map(SQLiteSectorSource(self.db))
        with self.pg.transaction():
            self.pg.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            pgsource = PostgreSQLSectorSource(self.pg)
            self.assertEqual(pgsource.snapshot('2026-01-09'), SQLiteSectorSource(self.db).snapshot('2026-01-09'))
            self.assertEqual(build_sector_map(pgsource), expected)
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
            load_sector_market(self.db, self.pg)
        self.assertEqual(self.pg.execute('SELECT count(*) FROM sector_market_prices').fetchone()[0], 9)
        self.assertEqual(self.pg.execute('SELECT count(*) FROM sector_market_membership').fetchone()[0], 3)


if __name__ == '__main__':
    unittest.main()
