from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest

from security.trial_quota import InvalidTransition, QuotaExceeded, TrialPolicy, TrialQuota


def digest(n):
    return f'{n:064x}'


class TrialQuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'trial.sqlite'
        self.now = datetime(2026, 1, 1, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        self.store = self.make_store()

    def make_store(self, **limits):
        policy = dict(per_network_day_limit=100, global_day_limit=100, max_in_flight=100)
        policy.update(limits)
        return TrialQuota(self.path, policy=TrialPolicy(**policy), clock=lambda: self.now)

    def reserve(self, actor=1, network=1):
        return self.store.reserve(actor_hash=digest(actor), network_hash=digest(network))

    def finish(self, reservation):
        self.store.mark_started(reservation)
        self.store.finish(reservation)

    def race(self, operation):
        def attempt(n):
            try:
                return operation(n)
            except QuotaExceeded:
                return None
        with ThreadPoolExecutor(max_workers=12) as pool:
            return [v for v in pool.map(attempt, range(24)) if v is not None]

    def test_explicit_init_permissions_and_unrelated_db(self):
        self.assertFalse(self.path.exists())
        with self.assertRaises(sqlite3.OperationalError):
            self.reserve()
        self.assertFalse(self.path.exists())
        self.store.initialize()
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.path.chmod(0o644)
        self.store.initialize()
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        other = Path(self.tmp.name) / 'other.sqlite'
        with sqlite3.connect(other) as conn:
            conn.execute('CREATE TABLE original (value TEXT)')
        other.chmod(0o644)
        original = other.read_bytes()
        store = TrialQuota(other, policy=self.store.policy)
        with self.assertRaises(ValueError):
            store.initialize()
        self.assertEqual(other.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(other.stat().st_mode), 0o644)
        with self.assertRaises(FileNotFoundError):
            TrialQuota(Path(self.tmp.name) / 'missing' / 'db', policy=self.store.policy).initialize()

    def test_concurrent_init_and_actor_limit(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.make_store().initialize(), range(24)))
        reservations = self.race(lambda _: self.make_store().reserve(actor_hash=digest(1), network_hash=digest(1)))
        self.assertEqual(len(reservations), 3)
        self.assertEqual(len(set(reservations)), 3)
        for reservation in reservations:
            self.finish(reservation)
        self.now += 86400
        with self.assertRaises(QuotaExceeded) as caught:
            self.reserve()
        self.assertEqual(caught.exception.reason, 'actor')

    def test_network_and_global_limits_across_distinct_actors(self):
        self.store = self.make_store(per_network_day_limit=2, global_day_limit=3)
        self.store.initialize()
        self.finish(self.reserve(1))
        self.finish(self.reserve(2))
        with self.assertRaises(QuotaExceeded) as caught:
            self.reserve(3)
        self.assertEqual(caught.exception.reason, 'network_day')
        self.finish(self.reserve(3, 2))
        with self.assertRaises(QuotaExceeded) as caught:
            self.reserve(4, 3)
        self.assertEqual(caught.exception.reason, 'global_day')
        self.now += 2
        self.assertIsNotNone(self.reserve(4))

    def test_parallel_network_and_global_admission(self):
        self.store = self.make_store(per_network_day_limit=2, global_day_limit=3)
        self.store.initialize()
        self.assertEqual(len(self.race(lambda n: self.reserve(n + 1))), 2)
        self.assertEqual(len(self.race(lambda n: self.reserve(n + 100, n + 100))), 1)

    def test_parallel_inflight_and_midnight(self):
        self.store = self.make_store(max_in_flight=2)
        self.store.initialize()
        reservations = self.race(lambda n: self.reserve(n + 1, n + 1))
        self.assertEqual(len(reservations), 2)
        self.store.mark_started(reservations[0])
        self.now += 86400 * 30
        with self.assertRaises(QuotaExceeded) as caught:
            self.reserve(100, 100)
        self.assertEqual(caught.exception.reason, 'in_flight')
        self.store.finish(reservations[0])
        self.assertIsNotNone(self.reserve(100, 100))

    def test_transitions_refund_only_before_start(self):
        self.store = self.make_store(per_actor_limit=1, per_network_day_limit=1, global_day_limit=1, max_in_flight=1)
        self.store.initialize()
        reservation = self.reserve()
        with self.assertRaises(InvalidTransition):
            self.store.finish(reservation)
        self.assertTrue(self.store.release_before_start(reservation))
        self.assertFalse(self.store.release_before_start(reservation))
        with self.assertRaises(InvalidTransition):
            self.store.mark_started(reservation)
        replacement = self.reserve()
        self.assertTrue(self.store.mark_started(replacement))
        self.assertFalse(self.store.mark_started(replacement))
        with self.assertRaises(InvalidTransition):
            self.store.release_before_start(replacement)
        self.assertTrue(self.store.finish(replacement))
        self.assertFalse(self.store.finish(replacement))
        with self.assertRaises(InvalidTransition):
            self.store.release_before_start(replacement)
        with self.assertRaises(InvalidTransition):
            self.store.mark_started(replacement)
        with self.assertRaises(QuotaExceeded):
            self.reserve()
        with self.assertRaises(LookupError):
            self.store.finish(digest(999))

    def test_concurrent_start_release_has_one_winner(self):
        self.store.initialize()
        reservation = self.reserve()
        def transition(fn):
            try:
                return fn(reservation)
            except InvalidTransition:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(transition, [self.store.mark_started, self.store.release_before_start]))
        self.assertEqual(sum(outcomes), 1)

    def test_reservations_survive_store_recreation(self):
        self.store = self.make_store(max_in_flight=1)
        self.store.initialize()
        reservation = self.reserve()
        self.store.mark_started(reservation)
        self.store = self.make_store(max_in_flight=1)
        self.store.initialize()
        with self.assertRaises(QuotaExceeded) as caught:
            self.reserve(2, 2)
        self.assertEqual(caught.exception.reason, 'in_flight')
        self.assertTrue(self.store.finish(reservation))
        self.assertIsNotNone(self.reserve(2, 2))

    def test_reject_raw_identifiers_and_invalid_policy(self):
        self.store.initialize()
        for raw in ['127.0.0.1', 'cookie-value', 'question text', 'a' * 63, 'A' * 64, None]:
            with self.assertRaises(ValueError):
                self.store.reserve(actor_hash=raw, network_hash=digest(1))
            with self.assertRaises(ValueError):
                self.store.reserve(actor_hash=digest(1), network_hash=raw)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM trial_reservations').fetchone()[0], 0)
        for field in ['per_actor_limit', 'per_network_day_limit', 'global_day_limit', 'max_in_flight']:
            for bad in [0, -1, True, 1.5, 2**31]:
                with self.assertRaises(ValueError):
                    self.make_store(**{field: bad})


if __name__ == '__main__':
    unittest.main()
