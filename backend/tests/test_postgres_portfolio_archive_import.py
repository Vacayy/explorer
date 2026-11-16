import os
import sqlite3
import unittest

from pipeline.postgres_ingest_rebuild_fixture import rebuild
from pipeline.postgres_portfolio_archive_import import PortfolioArchiveConflict, import_principle_archive
from pipeline.postgres_portfolio_read_fixture import import_read_snapshot, read_portfolio_tool
import tests.test_postgres_ingest_fixture as fixtures


@unittest.skipUnless(os.getenv('REFACTOR_TEST_DISPOSABLE') == '1', 'disposable fixture required')
class PortfolioArchiveImportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.IngestFixtureTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        with self.fixture.pg() as pg:
            rebuild(pg)
        self.source = sqlite3.connect(':memory:')
        self.addCleanup(self.source.close)
        self.source.executescript('''
          CREATE TABLE portfolio_principles(id INTEGER PRIMARY KEY,text TEXT NOT NULL,rules_json TEXT NOT NULL,created_at TEXT,notes_json TEXT);
          CREATE TABLE portfolio_principle_state(key TEXT PRIMARY KEY,since TEXT);
          CREATE TABLE portfolio_alerts_sent(key TEXT PRIMARY KEY,sent_at TEXT);
          INSERT INTO portfolio_principles VALUES(7,'원칙','[]','2026-01-01','["메모"]');
          INSERT INTO portfolio_principle_state VALUES('7:0:cash','2026-01-02');
          INSERT INTO portfolio_alerts_sent VALUES('7:0:cash','2026-01-03');
        ''')

    def test_preserves_all_fields_and_refuses_overwrite(self):
        with self.fixture.pg() as pg:
            counts = import_principle_archive(self.source, pg)
        self.assertEqual(counts, {'portfolio_principles': 1, 'portfolio_principle_state': 1, 'portfolio_alerts_sent': 1})
        with self.fixture.pg() as pg:
            row = pg.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='portfolio_principles'").fetchone()[0]
            self.assertEqual(row, {'id': 7, 'text': '원칙', 'rules_json': '[]', 'created_at': '2026-01-01', 'notes_json': '["메모"]'})
        with self.fixture.pg() as pg, self.assertRaises(PortfolioArchiveConflict):
            import_principle_archive(self.source, pg)

    def test_missing_source_table_rolls_back_every_table(self):
        self.source.execute('DROP TABLE portfolio_alerts_sent')
        with self.fixture.pg() as pg, self.assertRaises(PortfolioArchiveConflict):
            import_principle_archive(self.source, pg)
        with self.fixture.pg() as pg:
            self.assertEqual(pg.execute("SELECT count(*) FROM legacy_snapshot_tables WHERE table_name LIKE 'portfolio_%'").fetchone()[0], 0)

    def test_same_backup_portfolio_read_and_reimport_guard(self):
        self.source.executescript('''
          CREATE TABLE stock_groups(id INTEGER PRIMARY KEY,name TEXT,kind TEXT);
          CREATE TABLE portfolio_transactions(id INTEGER PRIMARY KEY,group_id INTEGER,trade_date TEXT,kind TEXT,stock_code TEXT,amount REAL,price REAL);
          CREATE TABLE portfolio_quotes(stock_code TEXT,price REAL,change_pct REAL,market_status TEXT,traded_at TEXT,fetched_at REAL);
          CREATE TABLE companies(stock_code TEXT,corp_name TEXT);
          CREATE TABLE stock_prices(id INTEGER PRIMARY KEY,stock_code TEXT,trade_date TEXT,close REAL);
          INSERT INTO stock_groups VALUES(1,'포트폴리오','portfolio');
          INSERT INTO portfolio_transactions VALUES(1,1,'2026-01-01','deposit',NULL,1000,NULL);
          INSERT INTO portfolio_transactions VALUES(2,1,'2026-01-02','buy','123456',500,100);
          INSERT INTO companies VALUES('123456','시험 회사');
          INSERT INTO stock_prices VALUES(1,'123456','2026-01-02',100);
          INSERT INTO stock_prices VALUES(2,'123456','2026-01-03',110);
        ''')
        with self.fixture.pg() as pg:
            counts = import_read_snapshot(self.source, pg)
        self.assertEqual((counts['portfolio_transactions'], counts['portfolio_principles'], counts['stock_prices']), (2, 1, 2))
        result = read_portfolio_tool(self.fixture.pg)
        self.assertEqual([item['kind'] for item in result.items], ['portfolio', 'principles'])
        self.assertIn('시험 회사', result.items[0]['text'])
        self.assertIn('원칙', result.items[1]['text'])
        from pipeline.postgres_chat_tools import PostgreSQLChatTools, UnsupportedPostgresChatTool
        without_owner = PostgreSQLChatTools(self.fixture.pg, None, allow_lexical_only=True)
        with self.assertRaises(UnsupportedPostgresChatTool):
            without_owner.run_tool({'name': 'get_portfolio', 'args': {}})
        owned = PostgreSQLChatTools(self.fixture.pg, None, allow_lexical_only=True,
                                    portfolio_provider=lambda: read_portfolio_tool(self.fixture.pg))
        self.assertEqual(owned.run_tool({'name': 'get_portfolio', 'args': {}}), result)
        with self.fixture.pg() as pg:
            pg.execute("DELETE FROM legacy_snapshot_rows WHERE table_name='stock_prices'")
            pg.execute("DELETE FROM legacy_snapshot_tables WHERE table_name='stock_prices'")
            generation = pg.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()[0]
            pg.execute('CREATE TABLE sector_market_metadata(singleton BOOLEAN,generation_id UUID,linked_document_generation BOOLEAN)')
            pg.execute('INSERT INTO sector_market_metadata VALUES (TRUE,%s,TRUE)', (generation,))
            pg.execute('CREATE TABLE sector_market_prices(stock_code TEXT,trade_date TEXT,close REAL)')
            pg.execute("INSERT INTO sector_market_prices VALUES ('123456','2026-01-02',100),('123456','2026-01-03',110)")
        self.assertEqual(read_portfolio_tool(self.fixture.pg), result)
        with self.fixture.pg() as pg:
            pg.execute('UPDATE sector_market_metadata SET linked_document_generation=FALSE')
        with self.assertRaises(PortfolioArchiveConflict):
            read_portfolio_tool(self.fixture.pg)
        with self.fixture.pg() as pg, self.assertRaises(PortfolioArchiveConflict):
            import_read_snapshot(self.source, pg)


if __name__ == '__main__':
    unittest.main()
