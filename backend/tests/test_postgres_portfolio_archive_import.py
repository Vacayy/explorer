import os
import sqlite3
import unittest

from pipeline.postgres_ingest_rebuild_fixture import rebuild
from pipeline.postgres_portfolio_archive_import import PortfolioArchiveConflict, import_principle_archive
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


if __name__ == '__main__':
    unittest.main()
