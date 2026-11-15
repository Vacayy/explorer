from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch
from models.earnings_season import SeasonOverview
from pipeline import earnings_chain as ec
from tests.test_earnings_upcoming import SCHEMA


class StoredUsSeasonTests(unittest.TestCase):
    def test_read_has_explicit_universe_core_and_no_lazy_write(self):
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.row_factory=sqlite3.Row
            conn.executescript(SCHEMA)
            conn.executescript('''ALTER TABLE earnings_events ADD COLUMN eps_surprise REAL;
                ALTER TABLE transcripts ADD COLUMN fetched_at TEXT;
                ALTER TABLE transcript_reactions ADD COLUMN created_at TEXT;
                CREATE TABLE season_themes(id INTEGER,season TEXT,sector TEXT,verdict TEXT,body_json TEXT,created_at TEXT);
                INSERT INTO earnings_events VALUES ('EXAMPLE',2026,'Q3','2026-11-01','2026Q3',1,5);
                INSERT INTO transcripts VALUES (1,1,'EXAMPLE',2026,'Q3','2026-11-01','2026-11-02');
                INSERT INTO transcript_reactions VALUES (1,'final','{"headline":"Stored headline"}','2026-11-02');
                INSERT INTO us_prices VALUES ('EXAMPLE','2026-10-30',100,100),('EXAMPLE','2026-11-02',105,100),('EXAMPLE','2026-11-03',110,100),
                  ('SPY','2026-10-30',100,100),('SPY','2026-11-02',100,100),('SPY','2026-11-03',100,100);
            ''')
            fs={'EXAMPLE':{'company_name':'Example','sector':'x:Example','market_cap':1000}}
            conn.commit();conn.execute('PRAGMA query_only=ON');before=conn.total_changes
            with patch.object(ec,'core_map',side_effect=AssertionError('lazy core')),patch.object(ec,'follows',side_effect=AssertionError('private universe')),patch.object(ec,'get_connection',side_effect=AssertionError('new connection')):
                result=ec.read_season_overview(conn,'2026Q3',fs=fs,core={'EXAMPLE':['cap']},last_run=None,today='2026-11-15',core_criteria={'cap':'Market cap'})
            SeasonOverview(**result)
            self.assertEqual(result['reported'][0]['d1'],10)
            self.assertEqual(result['counts']['reported'],1)
            self.assertEqual(result['core']['criteria'],{'cap':'Market cap'})
            self.assertEqual(conn.total_changes,before)
            self.assertEqual(conn.execute('SELECT count(*) FROM earnings_events').fetchone()[0],1)
