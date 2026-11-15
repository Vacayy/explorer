import json
import os
import sqlite3
import unittest
import uuid

import psycopg
from psycopg import sql

from pipeline.postgres_us_sectors import us_map as postgres_us_map
from pipeline.us_sectors import us_map as sqlite_us_map


@unittest.skipUnless(os.getenv('REFACTOR_TEST_DISPOSABLE') == '1', 'disposable fixture required')
class USSectorFixtureTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ['REFACTOR_POSTGRES_DSN']
        parts = psycopg.conninfo.conninfo_to_dict(self.dsn)
        if (parts.get('host'), parts.get('dbname'), parts.get('user')) != ('pg', 'fixture', 'fixture'):
            raise RuntimeError('Refusing non-fixture PostgreSQL')
        self.schema = 'refactor_fixture_' + uuid.uuid4().hex
        self.generation = uuid.uuid4()
        with psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
            c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
            c.execute('CREATE TABLE snapshot_metadata(singleton boolean, generation_id uuid)')
            c.execute('CREATE TABLE sector_market_metadata(singleton boolean, generation_id uuid, linked_document_generation boolean)')
            c.execute('CREATE TABLE sector_market_us_metadata(singleton boolean, generation_id uuid, classifications bigint)')
            c.execute('CREATE TABLE sector_market_us_classifications(ticker text,sector text,industry text)')
            c.execute('CREATE TABLE sector_market_benchmark_prices(ticker text,trade_date text,close double precision)')
            c.execute('CREATE TABLE legacy_snapshot_rows(table_name text,row_ordinal bigint,row_data jsonb)')
            c.execute('INSERT INTO snapshot_metadata VALUES (true,%s)', (self.generation,))
            c.execute('INSERT INTO sector_market_metadata VALUES (true,%s,true)', (self.generation,))
            c.execute('INSERT INTO sector_market_us_metadata VALUES (true,%s,1)', (self.generation,))
            c.execute("INSERT INTO sector_market_us_classifications VALUES ('NVDA','Technology','Semiconductors')")
            c.execute("INSERT INTO sector_market_benchmark_prices VALUES ('SPY','2026-01-01',100),('XLK','2026-01-01',200)")
            row = {'ticker': 'NVDA', 'company_name': 'Fixture', 'entity_id': 1, 'market_cap': 10, 'active': 1}
            c.execute("INSERT INTO legacy_snapshot_rows VALUES ('transcript_follow',0,%s::jsonb)", (json.dumps(row),))
        self.sqlite = sqlite3.connect(':memory:')
        self.sqlite.row_factory = sqlite3.Row
        self.sqlite.executescript("""
            CREATE TABLE sector_benchmark_prices(ticker text,trade_date text,close real);
            CREATE TABLE transcript_follow(ticker text,company_name text,entity_id integer,market_cap integer,active integer);
            CREATE TABLE us_ticker_sectors(ticker text,sector text,industry text);
            INSERT INTO sector_benchmark_prices VALUES ('SPY','2026-01-01',100),('XLK','2026-01-01',200);
            INSERT INTO transcript_follow VALUES ('NVDA','Fixture',1,10,1);
            INSERT INTO us_ticker_sectors VALUES ('NVDA','Technology','Semiconductors');
        """)

    def tearDown(self):
        self.sqlite.close()
        with psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def pg(self):
        return psycopg.connect(self.dsn, options=f'-c search_path={self.schema}')

    def test_map_matches_sqlite_and_rejects_stale_generation(self):
        expected = sqlite_us_map(self.sqlite)
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            self.assertEqual(postgres_us_map(c), expected)
        with self.pg() as c:
            c.execute('UPDATE sector_market_us_metadata SET generation_id=%s', (uuid.uuid4(),))
        with self.pg() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            with self.assertRaises(ValueError):
                postgres_us_map(c)


if __name__ == '__main__':
    unittest.main()
