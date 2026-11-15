import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipeline import kalshi
from routers import spine_home
from security import public_predictions as public
from security.access_boundary import PublicAccessBoundary
from tests.test_kalshi import V2_EVENT

class PublicPredictionsTests(unittest.TestCase):
    def test_public_cards_and_detail_never_read_pins_collect_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'markets.sqlite'
            with sqlite3.connect(path) as c:
                c.executescript(kalshi.SCHEMA)
                for ticker,rank,volume in [('A',0,10),('KXPIN-1',1,100)]:
                    c.execute('INSERT INTO kalshi_events(fetched_at,rank,category,series_ticker,event_ticker,title,recent_volume,outcomes_json) VALUES (?,?,?,?,?,?,?,?)',('2026-11-13 12:00:00',rank,'Politics','KXPIN',ticker,ticker,volume,json.dumps([dict(label='Yes',ticker='market',price=50)])))
                c.execute("INSERT INTO kalshi_pins(event_ticker,series_ticker) VALUES ('A','PRIVATE-CANARY')")
                c.execute('INSERT INTO kalshi_event_cache VALUES (?,?,?)',('KXPIN-1',json.dumps(V2_EVENT),'2026-11-13 12:00:00'))
            before=path.read_bytes()
            app=FastAPI();app.include_router(spine_home.router)
            app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies={('GET','/api/spine/home/predictions'):'public',('GET','/api/spine/home/predictions/{event_ticker}'):'public'})
            client=TestClient(app,base_url='https://beta.example')
            with patch.object(public,'DB_PATH',path),patch.object(kalshi,'fetch_event',side_effect=AssertionError('network')),patch.object(kalshi,'fetch_candles',side_effect=AssertionError('network')):
                cards=client.get('/api/spine/home/predictions');self.assertEqual(cards.status_code,200,cards.text)
                self.assertEqual(cards.json()['items'][0]['event_ticker'],'KXPIN-1')
                self.assertTrue(all(not e['pinned'] for e in cards.json()['items']))
                detail=client.get('/api/spine/home/predictions/KXPIN-1');self.assertEqual(detail.status_code,200,detail.text)
                self.assertNotIn('PRIVATE-CANARY',cards.text+detail.text)
                self.assertEqual(client.get('/api/spine/home/predictions/MISSING').status_code,404)
                self.assertEqual(client.post('/api/spine/home/predictions/A/pin',json={'series_ticker':'A','pinned':True}).status_code,404)
            client.close();self.assertEqual(before,path.read_bytes())

if __name__=='__main__':unittest.main()
