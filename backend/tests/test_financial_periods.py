"""Stored financial periods must represent calendar periods, never adjacent observations."""
import sqlite3
import unittest
from unittest.mock import patch
from services import dart_service as dart


class FinancialPeriodsTests(unittest.TestCase):
    def response(self, data, period='trailing', sj='IS', start=2024, end=2025):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.execute('CREATE TABLE financial_statements(corp_code, fs_div, sj_div, bsns_year, reprt_code, account_nm, thstrm_amount, ord)')
        conn.executemany('INSERT INTO financial_statements VALUES (?,?,?,?,?,?,?,?)',
                         [('corp', 'CFS', sj, year, code, '매출액', str(value), 1)
                          for year, code, value in data])
        with patch.object(dart, 'get_connection', return_value=conn):
            return dart._build_financial_response('corp', sj, period, start, end, 'CFS')

    def test_annual_yoy_does_not_bridge_missing_year(self):
        r = self.response([(2023, '11011', 100), (2025, '11011', 200)], 'annual', start=2023)
        self.assertEqual(r['rows'][0]['yoy'], [None, None])

    def test_trailing_sums_four_calendar_quarters_including_warmup(self):
        r = self.response([(2024, '11013', 10), (2024, '11012', 20),
                           (2024, '11014', 30), (2024, '11011', 100),
                           (2025, '11013', 50)], start=2025)
        self.assertEqual(r['periods'], ['25.03'])
        self.assertEqual(r['rows'][0]['values'], ['140'])

    def test_trailing_missing_quarter_is_not_partial_sum(self):
        r = self.response([(2024, '11013', 10), (2024, '11014', 30),
                           (2024, '11011', 100), (2025, '11013', 50)])
        self.assertEqual(r['rows'], [])

    def test_balance_sheet_trailing_remains_point_in_time(self):
        r = self.response([(2025, '11013', 50)], sj='BS')
        self.assertEqual(r['rows'][0]['values'], ['50'])

    def test_cash_flow_missing_prior_cumulative_is_unknown(self):
        r = self.response([(2025, '11012', 30)], 'quarterly', sj='CF')
        self.assertEqual(r['rows'], [])

    def test_cash_flow_trailing_uses_standalone_quarters(self):
        r = self.response([(2024, '11013', 10), (2024, '11012', 30),
                           (2024, '11014', 60), (2024, '11011', 100),
                           (2025, '11013', 50)], sj='CF')
        self.assertEqual(r['rows'][0]['values'], ['100', '140'])
