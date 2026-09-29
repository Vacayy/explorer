"""Risk: units, alignment, persistence, freshness and read-only route."""
import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipeline import risk
from models.risk import RiskResponse
from routers.spine_risk import router

NOW = datetime(2026, 9, 28, 14, tzinfo=timezone.utc)

def dates(n=30):
    out, d = [], date(2026, 8, 1)
    while len(out) < n:
        if risk.business_day(d): out.append(d.isoformat())
        d += timedelta(days=1)
    return out

class RiskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.sqlite'
        with self.connection() as c:
            c.executescript('''CREATE TABLE market_indicators(snapshot_date TEXT, indicator TEXT, value REAL, extra_json TEXT, PRIMARY KEY(snapshot_date,indicator)); CREATE TABLE cache_meta(cache_key TEXT PRIMARY KEY, fetched_at TEXT, expires_at TEXT);''')
        self.addCleanup(self.tmp.cleanup)
        for target in [risk, risk.cache_service]:
            p=patch.object(target,'get_connection',self.connection);p.start();self.addCleanup(p.stop)
    def connection(self):
        c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;return c
    def insert(self,key,points):
        with self.connection() as c:
            c.executemany('INSERT OR REPLACE INTO market_indicators VALUES (?,?,?,?)',[(d,'risk_'+key,v,json.dumps({'fetched_at':'2026-09-28T01:00:00+00:00'})) for d,v in points])
    def signal(self,n=23,rate_slope=-.015,credit_slope=3.75):
        ds=dates(n)
        items={'us10y':{'quality':'fresh','points':[(d,4.5+rate_slope*i) for i,d in enumerate(ds)]},'hy':{'quality':'fresh','points':[(d,300+credit_slope*i) for i,d in enumerate(ds)]}}
        return risk.evaluate_signal(items,date.fromisoformat(ds[-1])),items
    def test_bp_conversion_same_date_curve_without_fill(self):
        self.insert('us2y',[('2026-09-23',4),('2026-09-25',3.8)])
        self.insert('us10y',[('2026-09-23',3.5),('2026-09-24',3.6)])
        self.insert('hy',[('2026-09-24',4.2)])
        out=RiskResponse.model_validate(risk.get_risk(NOW));items={r.key:r for r in out.items}
        self.assertEqual(items['curve'].points,[('2026-09-23',-50)])
        self.assertEqual(items['hy'].value,420);self.assertEqual(items['us10y'].value,3.6)
    def test_exact_threshold_and_three_observations(self):
        s,_=self.signal();self.assertEqual((s['status'],s['consecutive'],s['rate_change_bp'],s['credit_change_bp']),('joint',3,-30,75))
    def test_short_history(self):
        self.assertEqual(self.signal(n=20)[0]['status'],'unavailable')
        self.assertEqual(self.signal(n=21)[0]['status'],'watch')
        self.assertEqual(self.signal(n=22)[0]['consecutive'],2)
    def test_rate_and_credit_states(self):
        self.assertEqual(self.signal(credit_slope=-1)[0]['status'],'rates')
        self.assertEqual(self.signal(rate_slope=.01)[0]['status'],'credit')
        self.assertEqual(self.signal(rate_slope=0,credit_slope=0)[0]['status'],'clear')
    def test_missing_observations_not_filled(self):
        _,items=self.signal();items['hy']['points'].pop(8)
        s=risk.evaluate_signal(items,date.fromisoformat(dates(23)[-1]))
        self.assertEqual(s['common_observations'],22);self.assertLessEqual(s['consecutive'],2)
    def test_weekend_month_end_not_counted(self):
        s,items=self.signal()
        for item in items.values():item['points'].append(('2026-08-30',999))
        self.assertEqual(risk.evaluate_signal(items,date.fromisoformat(dates(23)[-1])),s)
    def test_large_common_gap_defers(self):
        _,items=self.signal(n=28)
        for item in items.values():item['points']=item['points'][:10]+item['points'][15:]
        self.assertEqual(risk.evaluate_signal(items,date.fromisoformat(dates(28)[-1]))['status'],'unavailable')
    def test_essential_quality_defers(self):
        _,items=self.signal()
        for q in ('missing','stale','error'):
            items['hy']['quality']=q
            self.assertEqual(risk.evaluate_signal(items,date.fromisoformat(dates(23)[-1]))['status'],'unavailable')
    def test_holidays_and_dst(self):
        self.assertFalse(risk.business_day(date(2026,9,7)));self.assertFalse(risk.business_day(date(2026,4,3)))
        self.assertEqual(risk.expected_date(datetime(2026,9,8,14,tzinfo=timezone.utc)),date(2026,9,4))
        self.assertEqual(risk.expected_date(datetime(2026,3,9,14,tzinfo=timezone.utc)),date(2026,3,6))
        self.assertEqual(risk.lag_days('2026-09-04',date(2026,9,8)),1)
    def test_stale_uses_business_days(self):
        self.insert('vix',[('2026-09-23',20)]);self.insert('hy',[('2026-09-22',4)])
        items={i['key']:i for i in risk.get_risk(NOW)['items']}
        self.assertEqual(items['vix']['quality'],'fresh');self.assertEqual(items['hy']['quality'],'stale')
    def test_invalid_values_future_dates_deduplicated(self):
        self.assertEqual(risk.clean_rows('fear_greed',[('bad',1),('2026-09-25',101),('2026-09-26',float('nan')),('2026-09-27',0),('2026-09-29',50)],date(2026,9,28)),[('2026-09-27',0)])
        self.assertEqual(risk.clean_rows('vix',[('2026-09-25',20),('2026-09-25',21)],date(2026,9,28)),[('2026-09-25',21)])
    def test_failure_preserves_data_not_cached(self):
        self.insert('hy',[('2026-09-24',4.2)])
        with patch.object(risk,'_collect',side_effect=TimeoutError('secret-url')):out=risk._snapshot_one('hy')
        self.assertEqual(out['error'],'TimeoutError')
        with self.connection() as c:self.assertEqual(c.execute("SELECT value FROM market_indicators WHERE indicator='risk_hy'").fetchone()[0],4.2)
        self.assertFalse(risk.cache_service.is_cached('risk:hy:v2'))
    def test_success_cache(self):
        with patch.object(risk,'_collect',return_value=[('2026-01-02',4.2)]) as fetch:
            self.assertEqual(risk._snapshot_one('hy')['status'],'updated')
            self.assertEqual(risk._snapshot_one('hy')['status'],'cached');self.assertEqual(fetch.call_count,1)
    def test_long_history_is_not_truncated_on_read(self):
        self.insert('us2y',[('2000-01-03',6.38),('2026-09-24',4.87)])
        self.insert('us10y',[('2000-01-03',6.58),('2026-09-24',5.18)])
        self.insert('baa10y',[('2000-01-03',1.69),('2026-09-24',1.39)])
        items={i['key']:i for i in risk.get_risk(NOW)['items']}
        self.assertEqual(items['curve']['points'][0],('2000-01-03',20))
        self.assertEqual(items['baa10y']['points'][0],('2000-01-03',169))
    def test_full_backfill_once_then_incremental_refresh(self):
        with patch.object(risk,'_public_fred_history',return_value=[('2000-01-03',6.58)]) as fetch:
            risk._snapshot_one('us10y')
            self.assertGreater(fetch.call_args.kwargs['days'],20000)
            risk.cache_service.invalidate_cache('risk:us10y:v2')
            risk._snapshot_one('us10y')
            self.assertEqual(fetch.call_args.kwargs['days'],400)
    def test_oas_requests_source_supported_window(self):
        with patch.object(risk,'_public_fred_history',return_value=[]) as fetch:
            risk._collect('hy')
            self.assertEqual(fetch.call_args.kwargs['days'],3*366)
    def test_get_no_network_no_write(self):
        app=FastAPI();app.include_router(router)
        with patch.object(risk,'_collect',side_effect=AssertionError('network forbidden')):response=TestClient(app).get('/api/spine/risk')
        self.assertEqual(response.status_code,200);self.assertTrue(response.json()['empty'])
        with self.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM market_indicators').fetchone()[0],0)
    def test_sentiment_missing_does_not_block_signal(self):
        ds=dates(23);self.insert('us10y',[(d,4.5-.02*i) for i,d in enumerate(ds)]);self.insert('hy',[(d,3+.05*i) for i,d in enumerate(ds)])
        out=risk.get_risk(datetime.fromisoformat(ds[-1]+'T23:00:00+00:00'))
        self.assertEqual(out['signal']['status'],'joint');self.assertEqual(next(i for i in out['items'] if i['key']=='fear_greed')['quality'],'missing')

if __name__=='__main__':unittest.main()
