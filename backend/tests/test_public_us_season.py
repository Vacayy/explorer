from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pipeline import earnings_chain as ec
from security import public_us_season as public
from tests.test_earnings_upcoming import SCHEMA


class PublicUsSeasonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "public.sqlite"
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript(SCHEMA)
            conn.executescript('''
                ALTER TABLE earnings_events ADD COLUMN eps_surprise REAL;
                ALTER TABLE transcripts ADD COLUMN fetched_at TEXT;
                ALTER TABLE transcript_reactions ADD COLUMN created_at TEXT;
                CREATE TABLE season_themes(id INTEGER,season TEXT,sector TEXT,verdict TEXT,body_json TEXT,created_at TEXT);
                CREATE TABLE public_us_companies(ticker TEXT,company_name TEXT,sector TEXT,market_cap REAL);
                INSERT INTO public_us_companies VALUES ('PUBLIC','Public company','semis',1000);
                INSERT INTO earnings_events VALUES ('PUBLIC',2026,'Q3','2026-11-01','2026Q3',1,5);
                INSERT INTO earnings_events VALUES ('PRIVATE',2026,'Q3','2026-11-01','2026Q3',1,10);
                INSERT INTO transcripts VALUES (1,1,'PUBLIC',2026,'Q3','2026-11-01','2026-11-02');
                INSERT INTO transcripts VALUES (2,2,'PRIVATE',2026,'Q3','2026-11-01','2026-11-02');
                INSERT INTO transcript_reactions VALUES (1,'final','{"headline":"Public source"}','2026-11-02');
                INSERT INTO transcript_reactions VALUES (2,'final','{"headline":"Private canary"}','2026-11-02');
                INSERT INTO earnings_expectations (ticker,snapshot,issues_json,created_at) VALUES ('PRIVATE','d7','[]','2026-11-02');
                INSERT INTO season_themes VALUES (1,'2026Q3','private-sector','private canary','{}','2026-11-02');
                INSERT INTO us_prices VALUES ('PUBLIC','2026-10-30',100,100),('PUBLIC','2026-11-02',105,100),
                  ('PUBLIC','2026-11-03',110,100),('SMH','2026-10-30',100,100),('SMH','2026-11-02',100,100),('SMH','2026-11-03',100,100);
                INSERT INTO transcript_follow (ticker,company_name,core_pinned) VALUES ('PRIVATE','Private canary',1);
            ''')
            conn.commit()

    def test_public_scope_and_numeric_reaction_without_private_getters_or_writes(self):
        before = self.path.read_bytes()
        with patch.object(ec, 'get_connection', side_effect=AssertionError('private connection')), \
             patch.object(ec, 'follows', side_effect=AssertionError('private universe')), \
             patch.object(ec, 'core_map', side_effect=AssertionError('private core')), \
             patch.object(ec, '_kst_today', return_value='2026-11-02'):
            result = public.stored_season('2026Q3', path=self.path, today='2026-11-15').model_dump()
        self.assertEqual(result['counts']['followed'], 1)
        self.assertEqual(result['counts']['reported'], 1)
        self.assertEqual(result['reported'][0]['d1'], 10)
        self.assertEqual(result['reported'][0]['headline'], 'Public source')
        self.assertEqual(set(result['core']['criteria']), {'cap', 'dc_chain'})
        self.assertEqual(result['changes'], {'reactions':['PUBLIC'], 'transcripts':['PUBLIC'], 'themes':[], 'expectations':[]})
        self.assertNotIn('PRIVATE', str(result))
        self.assertEqual(self.path.read_bytes(), before)

    def test_connection_rejects_private_columns_tables_and_writes(self):
        with closing(public.connection(self.path)) as conn:
            for sql in ('SELECT * FROM transcript_follow', 'SELECT raw_doc_id FROM transcripts',
                        'DELETE FROM earnings_events', 'CREATE TABLE unwanted(x)',
                        'ATTACH DATABASE ":memory:" AS other'):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                    conn.execute(sql)

    def test_private_follow_and_pins_do_not_change_public_results(self):
        before = public.stored_season('2026Q3', path=self.path, today='2026-11-15')
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('UPDATE transcript_follow SET active=0, core_pinned=0')
            conn.execute("INSERT INTO transcript_follow (ticker,company_name,active,core_pinned,market_cap) VALUES ('PUBLIC','Private name',1,1,99999999)")
            conn.commit()
        after = public.stored_season('2026Q3', path=self.path, today='2026-11-15')
        self.assertEqual(before, after)

    def test_missing_snapshot_and_invalid_season_do_not_fallback(self):
        with patch.object(public, 'DB_PATH', None), self.assertRaises(sqlite3.OperationalError):
            public.stored_season()
        for season in ('2026Q0', '2026Q5', '2026Q3 trailing'):
            with self.subTest(season=season), self.assertRaises(ValueError):
                public.stored_season(season, path=self.path)
