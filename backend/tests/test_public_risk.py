from pathlib import Path
import sqlite3,tempfile,unittest,json
from datetime import datetime,timezone
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipeline import risk, credit_spreads as credit
from routers import spine_risk, spine_market, spine_credit
from security.access_boundary import PublicAccessBoundary
from security.public_risk import risk_connection, stored_risk
from security.public_market import market_connection

class PublicRiskTests(unittest.TestCase):
    def test_existing_routes_read_only_and_preserve_numeric_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'market.sqlite'
            with sqlite3.connect(path) as c:
                c.executescript('CREATE TABLE market_indicators(snapshot_date TEXT,indicator TEXT,value REAL,extra_json TEXT);'+credit.SCHEMA)
                for key,value in [('us2y',4),('us10y',5),('hy',3),('vix',20),('fear_greed',40)]:
                    c.execute('INSERT INTO market_indicators VALUES (?,?,?,?)',('2026-11-13','risk_'+key,value,'{}'))
                c.execute('INSERT INTO market_indicators VALUES (?,?,?,?)',('2026-11-13','risk_sync_vix',None,json.dumps({'error':'private-token-canary'})))
            before=path.read_bytes()
            now=datetime(2026,11,15,tzinfo=timezone.utc)
            data=stored_risk('3m',['vix','curve'],path=path,now=now)
            vix=next(i for i in data['items'] if i['key']=='vix')
            self.assertEqual(vix['value'],20);self.assertEqual(vix['quality'],'error')
            self.assertNotIn('canary',json.dumps(data))
            app=FastAPI()
            for r in (spine_risk,spine_market,spine_credit):app.include_router(r.router)
            paths=['risk','market-regime','credit','credit/history']
            app.add_middleware(PublicAccessBoundary,routes=app.router.routes,policies={('GET','/api/spine/'+p):'public' for p in paths})
            client=TestClient(app,base_url='https://beta.example')
            with patch('security.public_risk.DB_PATH',path),patch('security.public_market.DB_PATH',path),patch.object(credit,'ensure_schema',side_effect=AssertionError('DDL')),patch.object(credit,'source',side_effect=AssertionError('provider')),patch.object(spine_market,'snapshot_market',side_effect=AssertionError('collection')):
                for p in ['risk?range=3m&keys=vix,curve','market-regime','credit','credit/history?tickers=ORCL']:
                    response=client.get('/api/spine/'+p)
                    self.assertEqual(response.status_code,200,response.text)
                    self.assertNotIn('canary',response.text)
                self.assertEqual(client.post('/api/spine/risk/snapshot').status_code,404)
            client.close()
            conn=risk_connection(path)
            try:
                for sql in ['CREATE TABLE bad(a)','DELETE FROM market_indicators','SELECT name FROM sqlite_master']:
                    with self.assertRaises(sqlite3.DatabaseError):conn.execute(sql)
            finally:conn.close()
            self.assertEqual(before,path.read_bytes())

if __name__=='__main__':unittest.main()
