import copy
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.peer_monitor import parse_rows, publish, snapshot
import research.peer_monitor as monitor
from refresh_peer_monitor import refresh

CODES = ['000001', '000002', '000003']
CATALOG = dict(version='v1', groups=[dict(id='g', scope='product')],
               companies=[dict(code=code, groupIds=['g']) for code in CODES])


def now(day):
    return datetime.fromisoformat(day + 'T20:30:00').replace(tzinfo=ZoneInfo('Asia/Seoul'))


def payloads(end='2026-10-30', premium=0):
    # Calendar intentionally supplied by provider, not inferred from weekdays.
    days = [(date.fromisoformat(end) - timedelta(days=i)).isoformat() for i in range(70)]
    result = {}
    for code in CODES:
        rows = []
        for day in days:
            close = 100 + (premium if code == CODES[0] and day >= '2026-11-02' else 0)
            previous = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
            base = 100 + (premium if code == CODES[0] and previous >= '2026-11-02' else 0)
            rows.append(dict(tradingDateKst=day, regularMarketClosingPrice=str(close), basePrice=str(base),
                             regularMarketChangePrice=str(close-base), regularMarketChangeRate=str((close/base-1)*100),
                             closingPrice='999', tradingVolume='100'))
        result[code] = dict(items=rows)
    return result


class PeerMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def run_day(self, day, data=None, catalog=CATALOG):
        return refresh(self.root, catalog, dict(qualityIssues=[]), now(day),
                       fetch=lambda *_: data if data is not None else payloads(day))

    def current(self):
        return json.loads((self.root / 'current.json').read_text())

    def test_explicit_regular_close_and_cutoff(self):
        rows = parse_rows(payloads()[CODES[0]], '2026-10-30')
        self.assertEqual(rows['2026-10-30']['close'], 100)
        snap = snapshot(CATALOG, payloads('2026-11-02'), now('2026-11-02').replace(hour=15), [])
        self.assertEqual(snap['asOf'], '2026-11-01')

    def test_failure_preserves_last_good(self):
        self.run_day('2026-10-30')
        before = (self.root / 'current.json').read_bytes()
        bad = payloads('2026-11-02')
        bad[CODES[1]]['items'][0]['regularMarketChangePrice'] = '99'
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            self.run_day('2026-11-02', bad)
        self.assertEqual(before, (self.root / 'current.json').read_bytes())
        self.assertEqual(json.loads((self.root / 'last-attempt.json').read_text())['status'], 'error')

    def test_inconsistent_calendar_and_missing_member_rejected(self):
        data = payloads()
        data[CODES[1]] = payloads('2026-10-29')[CODES[1]]
        with self.assertRaisesRegex(ValueError, 'inconsistent'):
            self.run_day('2026-10-30', data)
        del data[CODES[2]]
        with self.assertRaisesRegex(ValueError, 'membership'):
            self.run_day('2026-10-30', data)

    def test_no_bootstrap_event_and_idempotent(self):
        self.run_day('2026-11-01', payloads())
        first = self.current()
        self.assertFalse(first['forwardObservation'])
        self.assertEqual(first['events'], [])
        self.assertTrue(all(row['observedStreak'] == 0 for row in first['observations']))
        self.assertEqual(self.run_day('2026-11-01', payloads())['status'], 'skipped')
        self.assertEqual(self.current(), first)

    def test_streak_only_advances_on_new_consecutive_observation(self):
        self.run_day('2026-11-01', payloads())
        for day in ['2026-11-02', '2026-11-03', '2026-11-04']:
            self.run_day(day, payloads(day, 10))
        row = next(row for row in self.current()['observations'] if row['code'] == CODES[0])
        self.assertEqual(row['observedStreak'], 3)
        self.assertEqual(self.current()['events'], [])
        self.assertEqual(self.current()['signalStatus'], 'held')
        self.run_day('2026-11-04', payloads('2026-11-04', 10))
        self.assertEqual(self.current()['observations'][0]['observedStreak'], 3)
        self.run_day('2026-11-06', payloads('2026-11-06', 10))
        self.assertEqual(self.current()['observations'][0]['observedStreak'], 1)
        self.assertEqual(self.current()['updateReason'], 'observation_gap')

    def test_revision_and_catalog_reset(self):
        self.run_day('2026-11-01', payloads())
        self.run_day('2026-11-02', payloads('2026-11-02', 10))
        self.run_day('2026-11-02', payloads('2026-11-02', 15))
        self.assertEqual(self.current()['updateReason'], 'same_date_revision')
        self.assertEqual(self.current()['observations'][0]['observedStreak'], 0)
        catalog = copy.deepcopy(CATALOG)
        catalog['companies'][0]['name'] = 'changed without version bump'
        self.run_day('2026-11-03', payloads('2026-11-03', 15), catalog)
        self.assertEqual(self.current()['updateReason'], 'catalog_or_policy_changed')
        self.assertEqual(self.current()['observations'][0]['observedStreak'], 0)

    def test_historical_revision_resets_streak(self):
        self.run_day('2026-11-01', payloads())
        self.run_day('2026-11-02', payloads('2026-11-02', 10))
        self.run_day('2026-11-03', payloads('2026-11-03', 15))
        self.assertEqual(self.current()['updateReason'], 'historical_revision')
        self.assertEqual(self.current()['observations'][0]['observedStreak'], 0)

    def test_recovers_archive_written_before_publication_crash(self):
        self.run_day('2026-11-01', payloads())
        original = monitor.atomic_json
        def crash(path, value):
            if path.name == 'current.json':
                raise OSError('simulated pointer failure')
            original(path, value)
        with patch.object(monitor, 'atomic_json', side_effect=crash):
            with self.assertRaises(OSError):
                self.run_day('2026-11-02', payloads('2026-11-02', 10))
        self.assertEqual(self.current()['prices']['asOf'], '2026-10-30')
        self.run_day('2026-11-02', payloads('2026-11-02', 10))
        self.assertEqual(self.current()['prices']['asOf'], '2026-11-02')
        self.assertEqual(len(list((self.root / 'snapshots').glob('*.json'))), 2)

    def test_known_issue_and_zero_volume_block_group(self):
        data = payloads()
        data[CODES[0]]['items'][3]['tradingVolume'] = '0'
        snap = snapshot(CATALOG, data, now('2026-11-01'), [])
        bundle, _ = publish(self.root, CATALOG, snap, now('2026-11-01'))
        self.assertTrue(all(row['excess20Pp'] is None for row in bundle['observations']))
        self.assertEqual(len(snap['qualityIssues']), 1)

    def test_corrected_quality_issue_and_a_b_a_revision(self):
        data = payloads()
        data[CODES[0]]['items'][3]['tradingVolume'] = '0'
        self.run_day('2026-11-01', data)
        first_key = self.current()['key']
        self.assertEqual(len(self.current()['prices']['qualityIssues']), 1)
        self.run_day('2026-11-01', payloads())
        self.assertEqual(self.current()['prices']['qualityIssues'], [])
        self.assertTrue(all(row['excess20Pp'] == 0 for row in self.current()['observations']))
        self.run_day('2026-11-01', data)
        self.assertNotEqual(self.current()['key'], first_key)
        self.assertEqual(len(list((self.root / 'snapshots').glob('*.json'))), 3)
        self.assertEqual(len(self.current()['prices']['qualityIssues']), 1)

    def test_backwards_date_and_stale_payload_rejected(self):
        self.run_day('2026-11-02')
        with self.assertRaisesRegex(ValueError, 'backwards'):
            self.run_day('2026-11-03', payloads('2026-11-01'))
        with self.assertRaisesRegex(ValueError, '7 calendar'):
            self.run_day('2026-11-20', payloads())

    def test_invalid_numbers_duplicates_and_missing_regular_field(self):
        for field, value in [('regularMarketClosingPrice', 'NaN'), ('basePrice', '0'), ('tradingVolume', '-1')]:
            data = payloads()[CODES[0]]
            data['items'][0][field] = value
            with self.assertRaises(ValueError):
                parse_rows(data, '2026-11-01')
        data = payloads()[CODES[0]]
        data['items'].append(data['items'][0])
        with self.assertRaises(ValueError):
            parse_rows(data, '2026-11-01')
        data = payloads()[CODES[0]]
        del data['items'][0]['regularMarketClosingPrice']
        with self.assertRaises(ValueError):
            parse_rows(data, '2026-11-01')


if __name__ == '__main__':
    unittest.main()
