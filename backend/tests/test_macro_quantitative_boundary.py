"""Keep public candidates independent of personal records before route exposure."""
import sqlite3
import unittest
from unittest.mock import patch
from pipeline import era, regimes
from models.regimes import RegimesResponse


class QuantitativeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');self.addCleanup(self.conn.close)
        self.conn.row_factory=sqlite3.Row
        self.conn.executescript('''CREATE TABLE market_indicators(indicator,snapshot_date,value);
            CREATE TABLE us_prices(stock_code,trade_date,close,fetched_at);
            CREATE TABLE era_checks(key,state,note,updated_at);''')
        self.conn.executemany('INSERT INTO market_indicators VALUES (?,?,?)',[
            ('era_cpi','2025-10-01',100),('era_cpi','2026-10-01',102),
            ('era_dff','2026-11-12',1),('risk_us10y','2026-11-12',1),
            ('risk_hy','2026-11-12',3),('era_hy_ey','2026-11-12',5),
            ('risk_vix','2026-11-12',12)])

    def test_quantitative_items_match_legacy_without_reading_personal_tables(self):
        baseline=era.layer_temperature(self.conn)
        self.assertEqual([i['key'] for i in baseline['items']],
                         ['real_policy','inflation','rate_level','hy_spread','hy_yield','vix'])
        self.assertEqual(baseline['verdict'],'hot')
        for key in era.CHECK_KEYS:
            self.conn.execute('INSERT INTO era_checks VALUES (?,?,?,?)',(key,'cold','PRIVATE_CANARY','2026-11-13'))
        changed=era.layer_temperature(self.conn)
        self.assertEqual(changed['items'],baseline['items'])
        self.assertNotEqual(changed['verdict'],baseline['verdict'])
        def authorizer(action,table,column,db,source):
            if action==sqlite3.SQLITE_READ and table not in {'market_indicators','us_prices'}:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        self.conn.set_authorizer(authorizer)
        with patch.object(era,'get_connection',side_effect=AssertionError('hidden connection')):
            result=era.quantitative_temperature(self.conn)
        self.assertEqual(result,baseline['items'])
        self.assertNotIn('PRIVATE_CANARY',str(result))
        self.assertFalse(any('note' in i or 'judged' in i for i in result))

    def test_empty_quantitative_items_do_not_invent_a_neutral_verdict(self):
        self.conn.execute('DELETE FROM market_indicators')
        self.assertEqual(era.quantitative_temperature(self.conn),[])

    def test_explicit_regime_snapshot_retains_confirmation_and_provisional_semantics(self):
        series=[(f'2000-01-{day:02d}',float(value)) for day,value in
                enumerate([100,110,120,100,96,90,110],start=3)]
        self.conn.executemany('INSERT INTO us_prices VALUES (?,?,?,?)',
            [(regimes.INDEX,d,v,'2026-11-13 00:00:00') for d,v in series])
        # get_regimes owns its connection, so use a wrapper whose close is harmless.
        class Borrowed:
            def execute(_, *args):return self.conn.execute(*args)
            def close(_):pass
        with patch.object(regimes,'get_connection',return_value=Borrowed()):
            legacy=regimes.get_regimes()
        with patch.object(regimes,'get_connection',side_effect=AssertionError('hidden DB')):
            result=regimes.regimes_from_series(series,[],'2026-11-13 00:00:00')
        self.assertEqual(result,legacy)
        RegimesResponse.model_validate(result)
        bear=result['phases'][1]
        self.assertEqual((bear['start'],bear['confirm_date'],bear['confirm_lag_days']),
                         ('2000-01-05','2000-01-07',2))
        self.assertFalse(bear['provisional']);self.assertTrue(result['phases'][-1]['provisional'])
        self.assertEqual(result['as_of'],'2000-01-09')
        self.assertEqual(regimes.regimes_from_series([],[])['current'],None)
