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
        with mock.patch.dict(sys.modules, {'pykrx': types.ModuleType('pykrx'), 'pykrx.website': types.ModuleType('w'),
                                           'pykrx.website.krx': types.ModuleType('k'),
                                           'pykrx.website.krx.market': types.SimpleNamespace(core=core),
                                           'pykrx.website.krx.market.core': core}):
            rows, bases = jobs.krx_market_day('2026-11-23')
        self.assertEqual(rows, [{'stock_code': '005930', 'trade_date': '2026-11-23', 'open': 1000, 'high': 1200, 'low': 990,
                                 'close': 1100, 'volume': 10, 'market_cap': 5000, 'shares': 5}])
        self.assertEqual(bases, {'005930': 1000})

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
