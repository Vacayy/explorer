from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests import test_kr_season as fixtures
from pipeline import kr_season
from routers import spine_transcript
from security import public_kr_season as public
from security.access_boundary import PublicAccessBoundary


class PublicKrSeasonTests(unittest.TestCase):
    def test_stored_read_matches_original_and_never_opens_private_connection(self):
        fixture = fixtures.OverviewTests(); fixture.setUp(); self.addCleanup(fixture.tearDown)
        today = date(2026, 11, 4)
        expected = kr_season.overview('2026Q3', today)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'snapshot.sqlite'
            fixture.conn.commit()
            with closing(sqlite3.connect(path)) as target:
                fixture.conn.backup(target)
                target.execute('CREATE TABLE public_kr_season_coverage(season TEXT PRIMARY KEY, backfilled INTEGER NOT NULL)')
                target.execute('CREATE TABLE public_kr_company_sectors(stock_code TEXT PRIMARY KEY, sector TEXT)')
                from pipeline.sector_overrides import effective_sectors
                target.executemany('INSERT INTO public_kr_company_sectors VALUES (?,?)', effective_sectors(fixture.conn).items())
                target.execute('CREATE TABLE cache_meta(secret TEXT)')
                target.commit()
            before = path.read_bytes()
            with patch.object(kr_season, 'get_connection', side_effect=AssertionError('private connection')), patch.object(kr_season, 'backfilled', side_effect=AssertionError('private coverage')):
                actual = public.stored_season('2026Q3', path=path, today=today)
            self.assertEqual(actual.model_dump(), expected)
            self.assertEqual(before, path.read_bytes())
            with closing(public.connection(path)) as conn:
                with self.assertRaises(sqlite3.DatabaseError): conn.execute('SELECT secret FROM cache_meta')
                with self.assertRaises(sqlite3.DatabaseError): conn.execute('DELETE FROM disclosures')
            app=FastAPI(); app.include_router(spine_transcript.router)
            app.add_middleware(PublicAccessBoundary, routes=app.router.routes,
                policies={('GET','/api/spine/transcript/season/kr'):'public'})
            with TestClient(app, base_url='https://beta.example') as client, patch.object(public,'DB_PATH',path):
                self.assertEqual(client.get('/api/spine/transcript/season/kr?season=2026Q3').status_code,200)
                self.assertEqual(client.get('/api/spine/transcript/season/kr?season=invalid').status_code,422)
