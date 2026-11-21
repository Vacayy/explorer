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
