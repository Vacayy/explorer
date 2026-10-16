"""지표 정본: 매크로·시장 국면·Risk API가 같은 지표·같은 날짜에 같은 값을 낸다.

레거시 행(macro_us10y=^TNX, vix, fear_greed)은 일부러 다른 값으로 남겨 둔다 — 읽기가 정본(risk_*)만 보는지 확인한다.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import indicator_canon, macro, market_regime, risk
from routers import spine_macro, spine_market, spine_risk

DAYS = ['2026-10-08', '2026-10-09', '2026-10-13', '2026-10-14']


class CanonicalIndicatorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'test.sqlite'
        with self.connection() as c:
            c.executescript('''CREATE TABLE market_indicators(snapshot_date TEXT, indicator TEXT, value REAL, extra_json TEXT,
                                 PRIMARY KEY(snapshot_date, indicator));
                               CREATE TABLE cache_meta(cache_key TEXT PRIMARY KEY, fetched_at TEXT, expires_at TEXT);
                               CREATE TABLE macro_signals(as_of TEXT PRIMARY KEY, signature TEXT, signal TEXT, headline TEXT,
                                 comment TEXT, model TEXT, created_at TEXT);''')
            rows = []
            for i, d in enumerate(DAYS):
                rows += [(d, 'risk_us10y', 5.16 + i * 0.01), (d, 'macro_us10y', 5.30 + i * 0.01),
                         (d, 'risk_us2y', 4.75 + i * 0.01), (d, 'macro_us2y', 4.10),
                         (d, 'risk_vix', 15.0 + i), (d, 'vix', 30.0 + i),
                         (d, 'risk_fear_greed', 40.0 - i), (d, 'fear_greed', 60.0 - i)]
            rows += [('2026-10-15', 'macro_us10y', 5.09), ('2026-10-15', 'fear_greed', 32.4)]   # 레거시만 있는 날
            c.executemany('INSERT INTO market_indicators VALUES (?,?,?,NULL)', rows)
        for target in (macro, market_regime, risk, risk.cache_service):
            p = patch.object(target, 'get_connection', self.connection)
            p.start()
            self.addCleanup(p.stop)
        app = FastAPI()
        for r in (spine_macro.router, spine_market.router, spine_risk.router):
            app.include_router(r)
        self.client = TestClient(app)

    def connection(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def test_all_endpoints_serve_the_canonical_value(self):
        risk_items = {i['key']: i for i in self.client.get('/api/spine/risk').json()['items']}
        macro_items = {i['key']: i for i in self.client.get('/api/spine/macro').json()['items']}
        us = self.client.get('/api/spine/market-regime').json()['us']

        for key in ('us10y', 'us2y'):
            self.assertEqual((macro_items[key]['as_of'], macro_items[key]['value']),
                             (risk_items[key]['as_of'], risk_items[key]['value']), key)
            self.assertEqual(dict(map(tuple, macro_items[key]['dated_series'])),
                             dict(map(tuple, risk_items[key]['points'])), key)
        self.assertEqual(macro_items['us10y']['value'], 5.19)
        self.assertEqual(us['fear_greed']['score'], risk_items['fear_greed']['value'])
        self.assertEqual(us['vix']['value'], risk_items['vix']['value'])
        self.assertEqual(dict(map(tuple, us['series']['osc'])), dict(map(tuple, risk_items['fear_greed']['points'])))
        self.assertEqual(dict(map(tuple, us['series']['vix'])), dict(map(tuple, risk_items['vix']['points'])))

    def test_collectors_no_longer_fetch_the_duplicates(self):
        with patch.object(macro, '_yf_history', return_value=[]) as yf, patch.object(macro, '_fred_history', return_value=[]), \
             patch.object(macro, '_refresh_signal'), patch.object(indicator_canon, 'refresh', return_value=[]) as canon:
            macro.snapshot_macro()
        self.assertNotIn('^TNX', [c.args[0] for c in yf.call_args_list])
        canon.assert_called_once_with(('us2y', 'us10y'))

        with patch.object(market_regime, '_yf_history', return_value=[]) as yf, \
             patch.object(market_regime, '_fear_greed_history') as fg, patch.object(market_regime, '_vkospi_history', return_value=[]), \
             patch.object(indicator_canon, 'refresh', return_value=['vix(HTTPError)']) as canon:
            result = market_regime.snapshot_market()
        fg.assert_not_called()
        self.assertNotIn('^VIX', [c.args[0] for c in yf.call_args_list])
        canon.assert_called_once_with(('fear_greed', 'vix'))
        self.assertIn('vix(HTTPError)', result['degraded'])

    def test_refresh_delegates_to_risk_collector_and_reports_failures(self):
        results = {'us2y': {'status': 'cached'}, 'us10y': {'status': 'error', 'error': 'TimeoutError'}}
        with patch.object(risk, '_snapshot_one', side_effect=lambda k: {'key': k, 'rows': 0, **results[k]}):
            self.assertEqual(indicator_canon.refresh(('us2y', 'us10y')), ['us10y(TimeoutError)'])


if __name__ == '__main__':
    unittest.main()
