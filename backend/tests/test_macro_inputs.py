"""New overview inputs: source parsing, units, dates, and collection registration."""
import io
import sqlite3
import unittest
from unittest.mock import MagicMock, patch
from pipeline import macro


class MacroInputsTests(unittest.TestCase):
    def test_fred_csv_keeps_percent_units_and_skips_missing(self):
        body = b'observation_date,DGS2\n2026-09-01,3.51\n2026-09-02,.\n2026-09-03,\n2026-09-04,3.62\n2026-09-05,NaN\n'
        with patch.object(macro.urllib.request, 'urlopen', return_value=io.BytesIO(body)) as fetch:
            self.assertEqual(macro._public_fred_history('DGS2', days=50000), [('2026-09-01',3.51),('2026-09-04',3.62)])
            self.assertTrue(fetch.call_args.args[0].full_url.startswith('https://fred.stlouisfed.org/graph/fredgraph.csv?'))

    def test_read_preserves_each_series_observation_date_and_units(self):
        conn=sqlite3.connect(':memory:'); conn.row_factory=sqlite3.Row
        conn.executescript('''CREATE TABLE market_indicators(snapshot_date TEXT, indicator TEXT, value REAL);
          INSERT INTO market_indicators VALUES ('2026-09-08','macro_us2y',3.51),
          ('2026-09-09','macro_usdkrw',1400.5),('2026-09-09','macro_us10y',4.2);''')
        with patch.object(macro,'get_connection',return_value=conn):
            data=macro.get_macro(with_signal=False)
        items={row['key']:row for row in data['items']}
        self.assertEqual(items['us2y']['value'],3.51)
        self.assertEqual(items['us2y']['fmt'],'pct')
        self.assertEqual(items['us2y']['as_of'],'2026-09-08')
        self.assertEqual(items['us2y']['dated_series'],[('2026-09-08',3.51)])
        self.assertEqual(items['us2y']['series'],[v for _,v in items['us2y']['dated_series']])
        self.assertEqual(items['usdkrw']['value'],1400.5)
        self.assertEqual(items['usdkrw']['as_of'],'2026-09-09')
        self.assertIn('금',data['degraded'])

    def test_snapshot_includes_new_sources_and_absorbs_individual_failure(self):
        conn=MagicMock()
        with patch.object(macro,'get_connection',return_value=conn), patch.object(macro,'_refresh_signal'), \
             patch.object(macro,'_yf_history',return_value=[('2026-09-09',1400)]) as yf, \
             patch.object(macro,'_fred_history',return_value=[]), \
             patch.object(macro,'_public_fred_history',side_effect=TimeoutError):
            result=macro.snapshot_macro()
        self.assertIn('usdkrw',result['indicators'])
        self.assertIn('us2y(TimeoutError)',result['degraded'])
        self.assertIn(unittest.mock.call('KRW=X'),yf.call_args_list)

if __name__=='__main__': unittest.main()
