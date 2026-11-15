from contextlib import closing
from pathlib import Path
from datetime import date
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import earnings_chain as ec
from security import public_us_season as public
from security.access_boundary import PublicAccessBoundary
from routers import spine_transcript
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
                ALTER TABLE public_us_companies ADD COLUMN fiscal_year_end TEXT;
                UPDATE public_us_companies SET fiscal_year_end='12-31';
                ALTER TABLE transcripts ADD COLUMN provider TEXT;
                ALTER TABLE season_themes ADD COLUMN tickers TEXT;
                CREATE TABLE public_us_coverage(ticker TEXT,has_release INTEGER,extracted_docs INTEGER,failed_docs INTEGER);
                INSERT INTO public_us_coverage VALUES ('PUBLIC',1,2,0),('PRIVATE',1,9999,9999);
                CREATE TABLE call_momentum(ticker TEXT,event_date TEXT,score REAL,status TEXT,reasons TEXT,first_candidate_at TEXT,summary TEXT,computed_at TEXT);
                CREATE TABLE public_transcript_text(transcript_id INTEGER PRIMARY KEY,body TEXT,digest TEXT);
                INSERT INTO public_transcript_text VALUES (1,'Public transcript body','Stored transcript summary'),(2,'Private canary','Private canary');
                CREATE TABLE public_us_calendar(ticker TEXT,last_report_date TEXT,next_report_date TEXT,checked_at TEXT,latest_results_date TEXT);
                INSERT INTO public_us_calendar VALUES ('PUBLIC','2026-11-01','2026-12-01','2026-11-02','2026-11-01');
                INSERT INTO earnings_events VALUES ('PUBLIC',2026,'Q4','2026-12-01','2026Q3',0,NULL);
            ''')
            conn.executemany('INSERT INTO call_momentum VALUES (?,?,7,?,\'{}\',NULL,?,?)', [
                ('PUBLIC',date.today().isoformat(),'candidate','Public summary','2026-11-01'),
                ('PRIVATE',date.today().isoformat(),'candidate','Private canary','2099-01-01')])
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

    def test_public_http_route_and_invalid_season(self):
        app = FastAPI()
        app.include_router(spine_transcript.router)
        app.add_middleware(PublicAccessBoundary, routes=app.router.routes,
                           policies={('GET', '/api/spine/transcript/season'): 'public'})
        before = self.path.read_bytes()
        with TestClient(app, base_url='https://beta.example') as client, patch.object(public, 'DB_PATH', self.path), \
             patch.object(ec, 'season_overview', side_effect=AssertionError('private season')):
            response = client.get('/api/spine/transcript/season?season=2026Q3')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['counts']['followed'], 1)
            self.assertEqual(client.get('/api/spine/transcript/season?season=2026Q9').status_code, 422)
            self.assertEqual(client.post('/api/spine/transcript/season').status_code, 404)
        self.assertEqual(before, self.path.read_bytes())

    def test_sector_momentum_recent_share_public_universe_and_do_not_write(self):
        from models.earnings_season import SectorDetail
        from routers.spine_transcript import MomentumResponse, RecentCall
        before = self.path.read_bytes()
        with patch.object(ec, 'get_connection', side_effect=AssertionError('private connection')), \
             patch.object(ec, 'core_map', side_effect=AssertionError('private core')):
            sector = public.stored_sector('semis','2026Q3',path=self.path,today='2026-11-15')
            SectorDetail(**sector)
            self.assertEqual({c['ticker'] for c in sector['companies']}, {'PUBLIC'})
            self.assertEqual(sector['companies'][0]['d1'],10)
            momentum = public.stored_momentum(path=self.path)
            MomentumResponse(**momentum)
            self.assertEqual(momentum['season']['reported'],1)
            self.assertEqual([c['ticker'] for c in momentum['candidates']],['PUBLIC'])
            self.assertEqual(momentum['coverage'],{'universe':1,'with_releases':1,'with_transcripts':1,'extracted_docs':2,'failed_docs':0,'comparable':1})
            self.assertEqual(momentum['as_of'],'2026-11-01')
            self.assertFalse(momentum['sec_configured'])
            recent=public.stored_recent(3650,40,path=self.path)
            for row in recent: RecentCall(**row)
            self.assertEqual([r['ticker'] for r in recent],['PUBLIC'])
            self.assertTrue(recent[0]['has_digest'])
            self.assertNotIn('digest',recent[0])
            self.assertNotIn('Private canary',str((sector,momentum,recent)))
        self.assertEqual(before,self.path.read_bytes())

    def test_public_transcript_text_history_upcoming_and_missing_private_ids(self):
        from models.earnings_chain import ChainDetail, UpcomingChain
        from routers.spine_transcript import Detail, FollowRow, QuarterRow
        before = self.path.read_bytes()
        with patch.object(ec,'get_connection',side_effect=AssertionError('private connection')), \
             patch.object(ec,'follows',side_effect=AssertionError('private follows')), \
             patch.object(ec,'latest_expectation',side_effect=AssertionError('private expectation')):
            rows=public.stored_companies(path=self.path)
            for row in rows: FollowRow(**row)
            self.assertEqual([r['ticker'] for r in rows],['PUBLIC'])
            self.assertEqual(rows[0]['n_calls'],1)
            for row in public.stored_quarters('PUBLIC',path=self.path): QuarterRow(**row)
            d=Detail(**public.stored_detail(1,path=self.path))
            self.assertEqual(d.body,'Public transcript body')
            self.assertEqual(d.digest,'Stored transcript summary')
            chain=ChainDetail(**public.stored_chain(1,path=self.path,today='2026-11-15'))
            self.assertEqual(chain.mentions,[])
            self.assertIsNone(chain.expectation)
            self.assertEqual(chain.history[0].d1,10)
            upcoming=UpcomingChain(**public.stored_upcoming('PUBLIC',path=self.path,today='2026-11-15'))
            self.assertEqual(upcoming.event_date,'2026-12-01')
            self.assertEqual(upcoming.days_to_event,16)
            self.assertIsNone(upcoming.expectation)
            for action in (lambda:public.stored_detail(2,path=self.path), lambda:public.stored_chain(2,path=self.path),lambda:public.stored_quarters('PRIVATE',path=self.path)):
                with self.assertRaises(LookupError): action()
        self.assertEqual(before,self.path.read_bytes())

    def test_prepared_provider_text_and_digest_flags_are_published(self):
        from routers.spine_transcript import Detail
        for provider in ('fool', 'alphavantage'):
            with closing(sqlite3.connect(self.path)) as conn:
                conn.execute("UPDATE transcripts SET provider=?,fetched_at=datetime('now') WHERE id=1", (provider,))
                conn.commit()
            result=Detail(**public.stored_detail(1,path=self.path))
            self.assertEqual(result.body,'Public transcript body')
            self.assertEqual(result.digest,'Stored transcript summary')
            self.assertEqual(result.content_status,'published')
            self.assertEqual(result.source_link_kind,'provider')
            self.assertTrue(result.source_url.startswith('https://'))
            self.assertTrue(public.stored_quarters('PUBLIC',path=self.path)[0]['has_digest'])
            self.assertTrue(public.stored_recent(path=self.path)[0]['has_digest'])
            self.assertTrue(public.stored_companies(path=self.path)[0]['latest']['has_digest'])

    def test_verified_article_link_preserves_prepared_text(self):
        url = 'https://www.fool.com/earnings/call-transcripts/2026/11/02/public-public-q3-2026-earnings-call-transcript/'
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE transcripts SET provider='fool' WHERE id=1")
            conn.execute('CREATE TABLE public_transcript_sources(transcript_id INTEGER PRIMARY KEY,ticker TEXT,fiscal_year INTEGER,fiscal_period TEXT,call_date TEXT,provider TEXT,url TEXT)')
            conn.execute('INSERT INTO public_transcript_sources VALUES(1,?,?,?,?,?,?)', ('PUBLIC',2026,'Q3','2026-11-01','fool',url))
        before = self.path.read_bytes()
        result = public.stored_detail(1,path=self.path)
        self.assertEqual((result['source_url'],result['source_link_kind']), (url,'article'))
        self.assertEqual((result['body'],result['digest'],result['content_status']), ('Public transcript body','Stored transcript summary','published'))
        self.assertEqual(before,self.path.read_bytes())
        for bad in ['https://[/',url.replace('www.fool.com','www.fool.com.evil.test'),url.replace('https:','http:'),url.replace('/public-public-q3','/public-public-q2'),url+'?token=private',url.replace('www.fool.com','user@www.fool.com')]:
            with closing(sqlite3.connect(self.path)) as conn, conn:
                conn.execute('UPDATE public_transcript_sources SET url=?',(bad,))
            self.assertEqual(public.stored_detail(1,path=self.path)['source_link_kind'],'provider')
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE public_transcript_sources SET url=?,call_date='2026-10-01'",(url,))
        self.assertEqual(public.stored_detail(1,path=self.path)['source_link_kind'],'provider')

    def test_stored_momentum_prose_is_preserved_for_transcripts_and_releases(self):
        import json
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("UPDATE call_momentum SET reasons=?,summary='RESTRICTED_CANARY' WHERE ticker='PUBLIC'",
                (json.dumps({'sources':['release','transcript'],'drivers':[{'name':'RESTRICTED_CANARY'}],
                             'extra':'RESTRICTED_CANARY'}),))
            conn.commit()
        result=public.stored_momentum(path=self.path)
        self.assertIn('RESTRICTED_CANARY',json.dumps(result))
        row=result['candidates'][0]
        self.assertEqual(row['score'],7)
        self.assertEqual(row['summary'],'RESTRICTED_CANARY')
        self.assertEqual(row['drivers'][0]['name'],'RESTRICTED_CANARY')
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("UPDATE call_momentum SET reasons=?,summary='Release source summary' WHERE ticker='PUBLIC'",
                         (json.dumps({'sources':['release']}),))
            conn.commit()
        self.assertEqual(public.stored_momentum(path=self.path)['candidates'][0]['summary'],'Release source summary')

    def test_removed_text_preserves_company_quarter_and_price_detail(self):
        from routers.spine_transcript import Detail
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("UPDATE transcripts SET provider='fool' WHERE id=1")
            conn.execute('DELETE FROM public_transcript_text WHERE transcript_id=1')
            conn.commit()
        d=Detail(**public.stored_detail(1,path=self.path))
        self.assertEqual(d.ticker,'PUBLIC')
        self.assertEqual(d.content_status,'source_only')
        self.assertTrue(public.stored_chain(1,path=self.path,today='2026-11-15')['history'])
        self.assertEqual(len(public.stored_quarters('PUBLIC',path=self.path)),1)

    def test_public_call_http_routes_and_private_id_denial(self):
        app=FastAPI(); app.include_router(spine_transcript.router)
        paths=['/follow','/company/{ticker}','/detail/{transcript_id}','/chain/{transcript_id}','/chain/upcoming/{ticker}']
        app.add_middleware(PublicAccessBoundary,routes=app.router.routes,
                           policies={('GET','/api/spine/transcript'+p):'public' for p in paths})
        with TestClient(app,base_url='https://beta.example') as client,patch.object(public,'DB_PATH',self.path):
            for path in ('/follow','/company/PUBLIC','/detail/1','/chain/1'):
                response=client.get('/api/spine/transcript'+path)
                self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(client.get('/api/spine/transcript/detail/2').status_code,404)
            self.assertEqual(client.get('/api/spine/transcript/chain/2').status_code,404)
            self.assertEqual(client.post('/api/spine/transcript/detail/1/digest').status_code,404)
