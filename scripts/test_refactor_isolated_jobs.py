"""The isolated collection path without PG or network: stop rules per host, per-source rollback, outcomes, deltas."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import refactor_isolated_jobs as jobs
from pipeline import postgres_isolated_collect as iso


class NetworkTest(unittest.TestCase):
    def test_a_block_refuses_only_that_host(self):
        net = jobs.Network({'': 5})
        net.before('https://service.moea.gov.tw/a.csv')
        net.after(403, 'https://service.moea.gov.tw/a.csv')
        with self.assertRaises(jobs.Refused):
            net.before('https://service.moea.gov.tw/b.csv')
        net.before('https://www.wsts.org/x')  # another host goes on
        self.assertEqual(net.stopped, {'service.moea.gov.tw': 'service.moea.gov.tw answered 403'})

    def test_cap_by_domain_suffix(self):
        net = jobs.Network({'': 1, '.yahoo.com': 2})
        net.before('https://query1.finance.yahoo.com/a')  # each host has the domain's cap
        net.before('https://query2.finance.yahoo.com/b')
        net.before('https://query2.finance.yahoo.com/c')
        with self.assertRaises(jobs.Refused):
            net.before('https://query2.finance.yahoo.com/c')
        net.before('https://www.census.gov/x')
        with self.assertRaises(jobs.Refused):
            net.before('https://www.census.gov/y')


class _Run(jobs.Run):
    """A private file seeded directly (no PG)."""

    def __init__(self, rows):
        self.tables = ('ext_series',)
        self.path = Path(tempfile.mkdtemp()) / 'run.db'
        with sqlite3.connect(self.path) as conn:
            conn.execute('CREATE TABLE ext_series (series TEXT, period TEXT, value REAL, PRIMARY KEY (series, period))')
            conn.executemany('INSERT INTO ext_series VALUES (?,?,?)', rows)
            self.before = {'ext_series': iso.rows_by_key(conn, 'ext_series')}
        self.seeded = {'ext_series': len(rows)}

    def write(self, *row):
        with sqlite3.connect(self.path) as conn:
            conn.execute('INSERT OR REPLACE INTO ext_series VALUES (?,?,?)', row)


class _PriceRun(jobs.Run):
    """A private file with a stock_prices table (no PG)."""

    def __init__(self, rows):
        self.tables = ('stock_prices',)
        self.path = Path(tempfile.mkdtemp()) / 'run.db'
        with sqlite3.connect(self.path) as conn:
            conn.execute('CREATE TABLE stock_prices (id INTEGER PRIMARY KEY AUTOINCREMENT, stock_code TEXT, trade_date TEXT, '
                         'open INT, high INT, low INT, close INT, volume INT, market_cap INT, shares INT, fetched_at TEXT, '
                         'UNIQUE(stock_code, trade_date))')
            conn.executemany('INSERT INTO stock_prices (stock_code, trade_date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)', rows)

    def connect(self):
        return sqlite3.connect(self.path)


class RunSourcesTest(unittest.TestCase):
    def test_failed_source_rolled_back_and_its_gap_kept(self):
        run = _Run([('wsts', '2026-08', 1.0), ('tw', '2026-08', 5.0)])

        def wsts(r, _prior):
            r.write('wsts', '2026-09', 2.0)
            return 'ok', {}, []

        def tw(r, _prior):
            r.write('tw', '2026-09', 6.0)  # written before the block: must not be published
            raise jobs.Refused('service.moea.gov.tw answered 403')
        states, _ = jobs.run_sources(run, [('wsts', wsts), ('tw', tw)],
                                     {'tw': {'status': 'error', 'failing_since': '2026-11-17 01:00:00', 'attempts': 3}})
        rows, deleted = run.changes()['ext_series']
        self.assertEqual(rows, [{'series': 'wsts', 'period': '2026-09', 'value': 2.0}])
        self.assertEqual(deleted, [])
        self.assertEqual(states['wsts']['status'], 'ok')
        self.assertIsNone(states['wsts']['failing_since'])
        self.assertEqual((states['tw']['status'], states['tw']['failing_since'], states['tw']['attempts']),
                         ('error', '2026-11-17 01:00:00', 4))  # the gap keeps its start across runs and days

    def test_failed_source_names_what_it_leaves_unfilled(self):
        run = _Run([('tw', '2026-09', 5.0)])

        def tw(_r, _prior):
            raise jobs.Refused('service.moea.gov.tw answered 403')
        tw.pending = lambda r: ['tw after 2026-09']
        states, _ = jobs.run_sources(run, [('tw', tw)], {})
        self.assertEqual(states['tw']['gaps'], ['tw after 2026-09'])

    def test_rerun_after_recovery_publishes_the_gap_once(self):
        run = _Run([('tw', '2026-08', 5.0), ('tw', '2026-09', 6.0)])  # the earlier run's success is already seeded

        def tw(r, _prior):
            r.write('tw', '2026-09', 6.0)  # same value again: not a change
            r.write('tw', '2026-10', 7.0)
            return 'ok', {}, []
        states, _ = jobs.run_sources(run, [('tw', tw)], {'tw': {'status': 'error', 'failing_since': '2026-11-17 01:00:00'}})
        rows, _ = run.changes()['ext_series']
        self.assertEqual(rows, [{'series': 'tw', 'period': '2026-10', 'value': 7.0}])
        self.assertEqual((states['tw']['status'], states['tw']['failing_since']), ('ok', None))


class OutcomeTest(unittest.TestCase):
    def test_outcomes(self):
        ok, err = {'status': 'ok'}, {'status': 'error'}
        self.assertEqual(jobs.outcome_of({'a': ok}, {'ext_series': (3, 0)}), 'applied: ext_series +3/-0')
        self.assertTrue(jobs.outcome_of({'a': ok, 'b': err}, {'ext_series': (3, 0)}).startswith('partial: ext_series +3/-0; failed b'))
        self.assertTrue(jobs.outcome_of({'a': err}, {}).startswith('failed: every source failed'))


class SettleTest(unittest.TestCase):
    """A publication whose commit raised: settled from the run record, or the whole collection is held."""

    def test_unreachable_pg_holds_everything(self):
        def connect():
            raise OSError('connection refused')
        self.assertEqual(jobs.settle(connect, 'extseries', 't', 's', 'applied: x', OSError('lost'), {}, {}),
                         (None, 'held back: publication state unknown'))

    def test_committed_publication_is_found_by_token(self):
        from unittest import mock
        with mock.patch.object(iso, 'published', return_value=41):
            self.assertEqual(jobs.settle(lambda: object(), 'extseries', 't', 's', 'partial: x', OSError('lost'), {}, {}),
                             (41, 'partial: x'))

    def test_missing_publication_is_recorded_as_failed(self):
        from unittest import mock
        from pipeline import postgres_collect_runs
        with mock.patch.object(iso, 'published', return_value=None), \
                mock.patch.object(postgres_collect_runs, 'record', return_value=42) as record:
            run_id, outcome = jobs.settle(lambda: object(), 'extseries', 't', 's', 'applied: x', OSError('lost'), {}, {})
        self.assertEqual((run_id, outcome.split(':')[0]), (42, 'failed'))
        record.assert_called_once()


class DeltaTest(unittest.TestCase):
    def test_changed_new_and_removed(self):
        before = {('a',): {'k': 'a', 'v': 1}, ('b',): {'k': 'b', 'v': 1}}
        after = {('a',): {'k': 'a', 'v': 1}, ('c',): {'k': 'c', 'v': 2}}
        self.assertEqual(iso.delta(before, after), ([{'k': 'c', 'v': 2}], [('b',)]))


class JobRunsTest(unittest.TestCase):
    """Only a run's own job records are published, by id."""

    def test_records_above_the_floor_only(self):
        import refactor_collect_job as job
        path = Path(tempfile.mkdtemp()) / 'work.db'
        with sqlite3.connect(path) as work:
            work.execute('CREATE TABLE job_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT, status TEXT)')
            work.execute("INSERT INTO job_runs (job, status) VALUES ('tw_revenue', 'ok')")
            work.execute("INSERT INTO job_runs (job, status) VALUES ('prices', 'error')")  # a failed run's leftover
        floor = job.job_runs_floor(path)
        with sqlite3.connect(path) as work:
            work.execute("INSERT INTO job_runs (job, status) VALUES ('retail', 'ok')")  # this run
        self.assertEqual([r['job'] for r in job.new_job_runs(path, floor)], ['retail'])


class SharedPathGuardTest(unittest.TestCase):
    def test_owned_tables_refused_on_shared_path(self):
        import refactor_collect_job as job
        with self.assertRaises(job.trial.HeldBack):
            job.supplement_tables(None, {'job_runs', 'ext_series'})
        self.assertFalse(job.ISOLATED_JOBS & job.TABLE_JOBS)


class SchedulerTest(unittest.TestCase):
    def test_isolated_outcomes_do_not_hold(self):
        import refactor_collect_scheduler as scheduler
        from unittest import mock
        for outcome, expected in (('partial: x', True), ('failed: every source failed (a)', True),
                                  ('held back: publication state unknown', False)):
            line = '{"outcome": "%s"}' % outcome
            with mock.patch('refactor_collect_engine.run', return_value=(0, line)):
                self.assertEqual(scheduler._run_one('extseries', log=lambda *_: None), expected, outcome)


class PricesTest(unittest.TestCase):
    def _conn(self, rows):
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE stock_prices (stock_code TEXT, trade_date TEXT, open INT, high INT, low INT, close INT, '
                     'volume INT, PRIMARY KEY (stock_code, trade_date))')
        conn.execute('CREATE TABLE market_indicators (indicator TEXT, snapshot_date TEXT)')
        conn.executemany('INSERT INTO stock_prices VALUES (?,?,?,?,?,?,?)', rows)
        return conn

    def test_only_final_in_range_within_limit_closes_are_kept(self):
        conn = self._conn([('A', '2026-11-19', 100, 110, 95, 100, 10), ('A', '2026-11-20', 100, 104, 98, 102, 9),
                           ('B', '2026-11-19', 100, 100, 100, 100, 1), ('B', '2026-11-20', 140, 140, 140, 140, 1),
                           ('C', '2026-11-20', 50, 60, 55, 52, 1)])
        rows = [dict(zip(('stock_code', 'trade_date', 'open', 'high', 'low', 'close', 'volume'), r)) for r in (
            ('A', '2026-11-20', 100, 104, 98, 102, 9), ('B', '2026-11-20', 140, 140, 140, 140, 1),
            ('C', '2026-11-20', 50, 60, 55, 52, 1), ('A', '2026-11-21', 100, 104, 98, 102, 9))]
        kept, rejected = jobs.validate_prices(conn, rows, through='2026-11-20')
        self.assertEqual([r['stock_code'] for r in kept], ['A'])
        self.assertEqual({(c, why.split(' ')[0]) for c, _d, why in rejected},
                         {('B', '+40.0%'), ('C', 'outside'), ('A', 'not')})

    def test_gaps_follow_the_kospi_calendar_for_recently_quoted_stocks(self):
        from datetime import date
        conn = self._conn([('A', '2026-11-19', 1, 1, 1, 1, 1), ('B', '2026-11-18', 1, 1, 1, 1, 1),
                           ('B', '2026-11-19', 1, 1, 1, 1, 1), ('B', '2026-11-20', 1, 1, 1, 1, 1)])
        conn.executemany('INSERT INTO market_indicators VALUES (?,?)',
                         [('index_kospi', d) for d in ('2026-11-18', '2026-11-19', '2026-11-20')])
        self.assertEqual(jobs.price_gaps(conn, date(2026, 11, 21)), {'A': ['2026-11-18', '2026-11-20']})

    def test_beyond_limit_confirmed_by_krx_close_and_limits(self):
        from unittest import mock
        conn = self._conn([('0035S0', '2026-11-17', 1, 1, 1, 12950, 1), ('041510', '2026-11-17', 1, 1, 1, 76500, 1)])
        rows = [{'stock_code': '0035S0', 'trade_date': '2026-11-18', 'close': 17090},
                {'stock_code': '041510', 'trade_date': '2026-11-18', 'close': 99900}]
        rejected = [('0035S0', '2026-11-18', '+32.0% vs previous close'), ('041510', '2026-11-18', '+30.6% vs previous close')]
        krx = {'0035S0': {'close': 17090, 'change': 3940, 'base': 13150, 'kind': '4', 'previous': 13150},
               '041510': {'close': 87900, 'change': 11000, 'base': 76900, 'kind': '1', 'previous': 76900}}
        with mock.patch.object(jobs, 'krx_day', side_effect=lambda c, d: krx[c]), \
                mock.patch.object(jobs, 'corporate_actions', return_value=[]):
            confirmed, still, evidence = jobs.confirm_beyond_limit(conn, rejected, rows)
        self.assertEqual([r['stock_code'] for r in confirmed], ['0035S0'])
        self.assertEqual(evidence['0035S0 2026-11-18']['limits'], [9210, 17090])
        self.assertEqual(evidence['0035S0 2026-11-18']['stored_previous_close'], 12950)
        self.assertIn('≠ KRX regular close 87900', still[0][2])

    def test_krx_limits_round_inward_to_the_tick(self):
        self.assertEqual(jobs.krx_limits(5460), (3825, 7090))
        self.assertEqual(jobs.krx_limits(1220), (854, 1586))

    def test_krx_days_skip_done_and_closed_and_start_at_the_switch(self):
        from datetime import date
        prior = {'2026-11-23': {'status': 'done'}, '2026-11-24': {'status': 'missing'}, '2026-11-25': {'status': 'closed'}}
        self.assertEqual(jobs.krx_days(prior, '2026-11-27', today=date(2026, 11, 28), start='2026-11-23'),
                         ['2026-11-24', '2026-11-26', '2026-11-27'])
        self.assertEqual(jobs.krx_days({}, '2026-11-21', today=date(2026, 11, 21), start='2026-11-23'), [])

    def test_krx_bars_kept_whole_or_rejected(self):
        rows = [{'stock_code': 'A', 'trade_date': 'd', 'open': 100, 'high': 110, 'low': 95, 'close': 105},
                {'stock_code': 'B', 'trade_date': 'd', 'open': 100, 'high': 104, 'low': 95, 'close': 105},
                {'stock_code': 'C', 'trade_date': 'd', 'open': 100, 'high': 140, 'low': 95, 'close': 140}]
        kept, rejected = jobs.validate_krx(rows, {('A', 'd'): 100, ('B', 'd'): 100, ('C', 'd'): 100})
        self.assertEqual([r['stock_code'] for r in kept], ['A'])
        self.assertEqual([c for c, _d, _w in rejected], ['B', 'C'])

    def test_krx_market_day_maps_regular_session_and_skips_no_trade(self):
        import sys, types
        from unittest import mock
        record = lambda code, close, vol: {'ISU_SRT_CD': code, 'TDD_CLSPRC': close, 'CMPPREVDD_PRC': '100', 'TDD_OPNPRC': '1,000',  # noqa: E731
                                           'TDD_HGPRC': '1,200', 'TDD_LWPRC': '990', 'ACC_TRDVOL': vol, 'MKTCAP': '5,000', 'LIST_SHRS': '5'}
        class Frame(list):
            def to_dict(self, _orient):
                return list(self)
        fetch = mock.Mock(side_effect=lambda day, market: Frame([record('005930', '1,100', '10')] if market == 'STK'
                                                                 else [record('123450', '0', '0')] if market == 'KSQ' else []))
        core = types.SimpleNamespace(**{'전종목시세': lambda: types.SimpleNamespace(fetch=fetch)})
        with mock.patch.object(jobs, 'krx_login'), \
                mock.patch.dict(sys.modules, {'pykrx': types.ModuleType('pykrx'), 'pykrx.website': types.ModuleType('w'),
                                           'pykrx.website.krx': types.ModuleType('k'),
                                           'pykrx.website.krx.market': types.SimpleNamespace(core=core),
                                           'pykrx.website.krx.market.core': core}):
            rows, bases, markets = jobs.krx_market_day('2026-11-23')
        self.assertEqual(rows, [{'stock_code': '005930', 'trade_date': '2026-11-23', 'open': 1000, 'high': 1200, 'low': 990,
                                 'close': 1100, 'volume': 10, 'market_cap': 5000, 'shares': 5}])
        self.assertEqual(bases, {'005930': 1000})

    def test_pricefix_corrects_traded_removes_no_trade_holds_unlisted(self):
        import os
        from unittest import mock
        run = _PriceRun([('A', '2026-11-20', 1, 1, 1, 99, 5), ('Q', '2026-11-20', 1, 1, 1, 50, 0),
                         ('U', '2026-11-20', 1, 1, 1, 70, 3), ('A', '2026-11-19', 1, 1, 1, 98, 5)])
        rec = lambda code, close, vol: {'ISU_SRT_CD': code, 'TDD_CLSPRC': close, 'CMPPREVDD_PRC': '0', 'TDD_OPNPRC': close,  # noqa: E731
                                        'TDD_HGPRC': close, 'TDD_LWPRC': close, 'ACC_TRDVOL': vol, 'MKTCAP': '1', 'LIST_SHRS': '1'}
        listing = {'STK': [rec('A', '100', '7')] * 1 + [rec('S%03d' % i, '10', '1') for i in range(900)],
                   'KSQ': [rec('Q', '50', '0'), rec('N', '20', '3')] + [rec('K%04d' % i, '10', '1') for i in range(1600)],
                   'KNX': [rec('X%02d' % i, '10', '1') for i in range(60)]}
        with mock.patch.dict(os.environ, {'PRICEFIX_DATE': '2026-11-20'}), \
                mock.patch.object(jobs, 'krx_listing', return_value=listing):
            (name, correct), = jobs.pricefix_sources(None)
            status, detail, gaps = correct(run, {})
        self.assertEqual((status, detail['no_trade_removed'], detail['held_not_listed']), ('partial', 1, ['U']))
        with sqlite3.connect(run.path) as conn:
            rows = dict(conn.execute("SELECT stock_code, close FROM stock_prices WHERE trade_date='2026-11-20'"))
        self.assertEqual((rows['A'], rows.get('Q'), rows['U'], rows['N']), (100, None, 70, 20))  # U held unchanged
        with sqlite3.connect(run.path) as conn:
            stamp = conn.execute("SELECT fetched_at FROM stock_prices WHERE stock_code='A' AND trade_date='2026-11-20'").fetchone()
            conn.execute("UPDATE stock_prices SET fetched_at='before' WHERE trade_date='2026-11-20'")
        with mock.patch.dict(os.environ, {'PRICEFIX_DATE': '2026-11-20'}), \
                mock.patch.object(jobs, 'krx_listing', return_value=listing):
            (name, correct), = jobs.pricefix_sources(None)
            correct(run, {})
        with sqlite3.connect(run.path) as conn:  # the same KRX values again: nothing rewritten
            self.assertEqual({r[0] for r in conn.execute("SELECT fetched_at FROM stock_prices WHERE trade_date='2026-11-20'")}, {'before'})

    def test_pricefix_refuses_an_incomplete_listing(self):
        import os
        from unittest import mock
        run = _PriceRun([('A', '2026-11-20', 1, 1, 1, 99, 5)])
        with mock.patch.dict(os.environ, {'PRICEFIX_DATE': '2026-11-20'}), \
                mock.patch.object(jobs, 'krx_listing', return_value={'STK': [], 'KSQ': [], 'KNX': []}):
            (name, correct), = jobs.pricefix_sources(None)
            status, detail, _ = correct(run, {})
        self.assertEqual(status, 'error')
        self.assertIn('incomplete', detail['error'])

    def test_listing_day_judged_on_60_to_400_percent_of_the_offering_price(self):
        from unittest import mock
        rows = [{'stock_code': 'NEW', 'trade_date': '2026-11-17', 'open': 30000, 'high': 41000, 'low': 26000, 'close': 36000},
                {'stock_code': 'OLD', 'trade_date': '2026-11-17', 'open': 30000, 'high': 41000, 'low': 26000, 'close': 36000},
                {'stock_code': 'BIG', 'trade_date': '2026-11-17', 'open': 30000, 'high': 52000, 'low': 26000, 'close': 50000}]
        bases = {('NEW', '2026-11-17'): 12000, ('OLD', '2026-11-17'): 12000, ('BIG', '2026-11-17'): 12000}
        kept, rejected = jobs.validate_krx(rows, bases)
        self.assertEqual(kept, [])
        rows.append({'stock_code': 'MOVED', 'trade_date': '2026-11-17', 'open': 30000, 'high': 41000, 'low': 26000, 'close': 36000})
        bases[('MOVED', '2026-11-17')] = 12000
        rejected.append(('MOVED', '2026-11-17', 'outside the limits of base 12000'))
        markets = {('NEW', '2026-11-17'): 'KSQ', ('OLD', '2026-11-17'): 'KSQ', ('BIG', '2026-11-17'): 'KSQ', ('MOVED', '2026-11-17'): 'KSQ'}
        with mock.patch.object(jobs, 'previous_listing', return_value=('2026-11-14', {'OLD': 'KSQ', 'MOVED': 'KNX'})):
            confirmed, still, evidence = jobs.confirm_listing_days(rows, rejected, bases, markets)
        self.assertEqual([r['stock_code'] for r in confirmed], ['NEW', 'MOVED'])  # a KONEX-to-KOSDAQ transfer day too
        self.assertEqual(evidence['NEW 2026-11-17']['limits'], [7200, 48000])
        self.assertEqual({c: why.split('; ')[-1] for c, _d, why in still},
                         {'OLD': 'listed on 2026-11-14, not a listing day', 'BIG': 'listing day but outside 7200-48000'})

    def test_adjustment_only_where_the_base_price_was_reset(self):
        self.assertIsNone(jobs.adjustment('A', 'd', 1000, 1000))
        self.assertIsNone(jobs.adjustment('A', 'd', 1000, None))
        self.assertEqual(jobs.adjustment('304840', '2026-11-20', 1220, 561), ('304840', '2026-11-20', 1220 / 561, 1220, 561))

    def test_sweep_records_factors_and_stops_at_the_cap_without_skipping(self):
        import os
        from unittest import mock
        rec = lambda code, close, chg, vol='1': {'ISU_SRT_CD': code, 'TDD_CLSPRC': close, 'CMPPREVDD_PRC': chg, 'TDD_OPNPRC': close,  # noqa: E731
                                                'TDD_HGPRC': close, 'TDD_LWPRC': close, 'ACC_TRDVOL': vol, 'MKTCAP': '1', 'LIST_SHRS': '1'}
        days = {'2026-11-16': {'STK': [rec('A', '100', '0'), rec('B', '500', '0')]},
                '2026-11-17': {'STK': [rec('A', '102', '2'), rec('B', '110', '10')]}}  # B: base 100 after a 1:5 split
        net = jobs.Network({'': 10})
        pg = mock.Mock()
        pg.execute.return_value = []

        def listing(day):
            if day == '2026-11-18':
                net.stopped['data.krx.co.kr'] = 'data.krx.co.kr reached the request cap 10'
                return {}
            return days.get(day, {})
        with mock.patch.dict(os.environ, {'PRICEFACTORS_FROM': '2026-11-17', 'PRICEFACTORS_TO': '2026-11-20', 'PRICEFACTORS_PAUSE': '0'}), \
                mock.patch.object(jobs, 'krx_listing', side_effect=listing), \
                mock.patch.object(jobs, 'previous_listing', return_value=('2026-11-16', {'A': 'STK', 'B': 'STK'})):
            (name, sweep), = jobs.pricefactors_sources(net, pg)
            status, detail, gaps = sweep(None, {})
        self.assertEqual(sweep.adjustments, [('B', '2026-11-17', 0.2, 100, 500)])
        self.assertEqual((status, gaps[0]['next_day']), ('partial', '2026-11-18'))  # the refused day is next, not skipped

        def expired(day):
            if day == '2026-11-18':
                raise ValueError('Expecting value: line 13 column 1')  # KRX answered its login page
            return days.get(day, {})
        net.stopped.clear()
        with mock.patch.dict(os.environ, {'PRICEFACTORS_FROM': '2026-11-17', 'PRICEFACTORS_TO': '2026-11-20', 'PRICEFACTORS_PAUSE': '0'}), \
                mock.patch.object(jobs, 'krx_listing', side_effect=expired), \
                mock.patch.object(jobs, 'previous_listing', return_value=('2026-11-16', {'A': 'STK', 'B': 'STK'})):
            (name, sweep), = jobs.pricefactors_sources(net, pg)
            status, detail, gaps = sweep(None, {})
        self.assertEqual((status, gaps[0]['next_day'], detail['stopped'][:10]), ('partial', '2026-11-18', 'ValueError'))
        self.assertEqual(gaps[0]['last_done'], '2026-11-17')
        # the next run continues from the stored place (no PRICEFACTORS_FROM), and finishes
        with mock.patch.dict(os.environ, {'PRICEFACTORS_TO': '2026-11-18', 'PRICEFACTORS_PAUSE': '0'}), \
                mock.patch.object(jobs, 'krx_listing', side_effect=lambda d: {'STK': [rec('A', '104', '2'), rec('B', '111', '1')]}):
            (name, sweep), = jobs.pricefactors_sources(net, pg)
            status, detail, gaps = sweep(None, {'gaps': gaps})
        self.assertEqual((status, detail['until'], gaps), ('ok', '2026-11-18', [{'last_done': '2026-11-18', 'done': True}]))

    def test_sweep_keeps_its_place_when_the_first_lookup_fails(self):
        import os
        from unittest import mock
        prior = {'gaps': [{'last_done': '2021-10-22', 'next_day': '2021-10-25', 'previous_closes': {'A': 1}}]}
        with mock.patch.dict(os.environ, {'PRICEFACTORS_FROM': '2021-10-23', 'PRICEFACTORS_PAUSE': '0'}), \
                mock.patch.object(jobs, 'previous_listing', side_effect=jobs.KrxUnavailable('KRX login failed')):
            (name, sweep), = jobs.pricefactors_sources(jobs.Network({'': 5}), None)
            status, detail, gaps = sweep(None, prior)
        self.assertEqual((status, gaps[0]['next_day']), ('error', '2021-10-23'))  # nothing walked: the place is kept

    def test_krx_login_cooldown_makes_no_request(self):
        import os
        from unittest import mock
        mark = Path(tempfile.mkdtemp()) / 'cooldown'
        mark.write_text('2026-11-21 07:41:51 UTC (JSONDecodeError)')
        with mock.patch.object(jobs, 'KRX_COOLDOWN', mark):
            os.utime(mark, (0, 0))  # however old: held until an operator removes the mark
            with self.assertRaises(jobs.KrxUnavailable):
                jobs.krx_listing('2026-11-23')
            with mock.patch.dict(os.environ, {'KRX_ID': 'x', 'KRX_PW': 'y'}):
                try:
                    jobs.legacy_sources('retail')
                except Exception:  # noqa: BLE001 - only the account removal matters here
                    pass
                self.assertNotIn('KRX_ID', os.environ)  # retail runs without the KRX account while held

    def test_closed_through(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        seoul = ZoneInfo('Asia/Seoul')
        self.assertEqual(jobs.closed_through(datetime(2026, 11, 20, 15, 39, tzinfo=seoul)), '2026-11-19')
        self.assertEqual(jobs.closed_through(datetime(2026, 11, 20, 15, 40, tzinfo=seoul)), '2026-11-20')


class BriefingHoldAlertTest(unittest.TestCase):
    def test_once_a_day_in_the_window_and_only_while_held(self):
        from datetime import datetime
        from unittest import mock
        import refactor_collect_scheduler as scheduler
        directory = Path(tempfile.mkdtemp())
        hold, mark = directory / 'hold', directory / 'mark'
        sent = []

        def send(text):
            sent.append(text)
            return True
        at = lambda hm: datetime(2026, 11, 22, *hm, tzinfo=scheduler.SEOUL)  # noqa: E731
        with mock.patch.object(scheduler, 'HOLD', hold), mock.patch.object(scheduler, 'BRIEFING_ALERT_MARK', mark):
            self.assertFalse(scheduler.alert_held_briefing(at((6, 20)), log=lambda *_: None, send=send))  # not held
            hold.write_text('extseries 2026-11-21 21:00:00 UTC')
            self.assertFalse(scheduler.alert_held_briefing(at((6, 19)), log=lambda *_: None, send=send))
            self.assertTrue(scheduler.alert_held_briefing(at((6, 20)), log=lambda *_: None, send=send))
            self.assertFalse(scheduler.alert_held_briefing(at((6, 25)), log=lambda *_: None, send=send))  # once
            self.assertFalse(scheduler.alert_held_briefing(at((6, 30)), log=lambda *_: None, send=send))
            self.assertTrue(hold.exists())  # the hold is never touched
        self.assertEqual(len(sent), 1)
        self.assertIn('extseries', sent[0])

    def test_failed_send_is_tried_again(self):
        from datetime import datetime
        from unittest import mock
        import refactor_collect_scheduler as scheduler
        directory = Path(tempfile.mkdtemp())
        (directory / 'hold').write_text('prices')
        at = datetime(2026, 11, 22, 6, 21, tzinfo=scheduler.SEOUL)
        with mock.patch.object(scheduler, 'HOLD', directory / 'hold'), \
                mock.patch.object(scheduler, 'BRIEFING_ALERT_MARK', directory / 'mark'):
            self.assertFalse(scheduler.alert_held_briefing(at, log=lambda *_: None, send=lambda _t: False))
            self.assertTrue(scheduler.alert_held_briefing(at, log=lambda *_: None, send=lambda _t: True))


if __name__ == '__main__':
    unittest.main()
