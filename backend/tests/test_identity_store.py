import concurrent.futures
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest

from security.identity_store import IdentityStore


class IdentityStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'identity.sqlite'
        self.now = 1000
        self.store = IdentityStore(self.path, clock=lambda: self.now)

    def user(self, subject='subject-a'):
        return self.store.get_or_create_google_user('https://accounts.google.com', subject)

    def test_explicit_initialization_and_unrelated_db_refusal(self):
        self.assertFalse(self.path.exists())
        with self.assertRaises(sqlite3.OperationalError):
            self.user()
        self.assertFalse(self.path.exists())
        with sqlite3.connect(self.path) as conn:
            conn.execute('CREATE TABLE market_data (id INTEGER)')
        self.path.chmod(0o644)
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.store.initialize()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o644)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall(), [('market_data',)])

    def test_private_permissions_new_and_existing(self):
        self.store.initialize()
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        a = self.user()
        self.path.chmod(0o644)
        self.store.initialize()
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(self.user(), a)

    def test_concurrent_initialize_and_missing_parent(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: IdentityStore(self.path).initialize(), range(24)))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(self.user().role, 'member')
        missing = Path(self.tmp.name) / 'missing' / 'identity.sqlite'
        with self.assertRaises(FileNotFoundError):
            IdentityStore(missing).initialize()
        self.assertFalse(missing.parent.exists())

    def test_identity_separation_default_role_and_repeat_init(self):
        self.store.initialize()
        a = self.user()
        self.store.initialize()
        self.assertEqual(a, self.user())
        self.assertEqual(a, self.store.get_or_create_google_user('accounts.google.com', 'subject-a'))
        self.assertNotEqual(a.id, self.user('subject-b').id)
        # There is intentionally no email input: email cannot merge subjects.
        self.assertEqual(a.role, 'member')
        for issuer, subject in [('https://evil.example', 'a'), ('accounts.google.com', ''), ('accounts.google.com', ' ' )]:
            with self.assertRaises(ValueError):
                self.store.get_or_create_google_user(issuer, subject)

    def test_concurrent_identity_creation_is_single_user(self):
        self.store.initialize()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(lambda _: self.user().id, range(24)))
        self.assertEqual(len(set(ids)), 1)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM users').fetchone()[0], 1)

    def test_session_hash_only_and_two_users(self):
        self.store.initialize()
        a, b = self.user(), self.user('b')
        first = self.store.issue_session(a.id, ttl_seconds=60)
        second = self.store.issue_session(b.id, ttl_seconds=60)
        self.assertNotEqual(first, second)
        self.assertEqual(self.store.resolve_session(first), a)
        self.assertEqual(self.store.resolve_session(second), b)
        with sqlite3.connect(self.path) as conn:
            persisted = '\n'.join(conn.iterdump())
        self.assertNotIn(first, persisted)
        self.assertNotIn(second, persisted)
        self.assertNotIn(first.encode(), self.path.read_bytes())
        for bad in ['', 'invalid', 'x' * 257, None]:
            self.assertIsNone(self.store.resolve_session(bad))
        self.store.revoke_session(first)
        self.store.revoke_session(first)
        self.assertIsNone(self.store.resolve_session(first))
        self.assertEqual(self.store.resolve_session(second), b)

    def test_expiry_boundary_and_cleanup(self):
        self.store.initialize()
        token = self.store.issue_session(self.user().id, ttl_seconds=60)
        self.now = 1059
        self.assertIsNotNone(self.store.resolve_session(token))
        self.now = 1060
        self.assertIsNone(self.store.resolve_session(token))
        self.assertEqual(self.store.expire_sessions(), 1)
        self.assertEqual(self.store.expire_sessions(), 0)

    def test_role_changes_and_disable_revoke_immediately(self):
        self.store.initialize()
        a = self.user()
        token = self.store.issue_session(a.id, ttl_seconds=60)
        self.store.set_role(a.id, 'operator')
        self.assertEqual(self.store.resolve_session(token).role, 'operator')
        self.store.set_role(a.id, 'member')
        self.assertEqual(self.store.resolve_session(token).role, 'member')
        self.store.set_enabled(a.id, False)
        self.assertIsNone(self.store.resolve_session(token))
        self.assertFalse(self.user().enabled)
        with self.assertRaises(PermissionError):
            self.store.issue_session(a.id, ttl_seconds=60)
        self.store.set_enabled(a.id, True)
        self.assertIsNone(self.store.resolve_session(token))
        self.assertIsNotNone(self.store.resolve_session(self.store.issue_session(a.id, ttl_seconds=60)))

    def test_invalid_management_and_session_requests(self):
        self.store.initialize()
        a = self.user()
        with self.assertRaises(ValueError):
            self.store.set_role(a.id, 'admin')
        with self.assertRaises(LookupError):
            self.store.set_role('missing', 'operator')
        with self.assertRaises(LookupError):
            self.store.set_enabled('missing', False)
        with self.assertRaises(ValueError):
            self.store.set_enabled(a.id, 1)
        with self.assertRaises(PermissionError):
            self.store.issue_session('missing', ttl_seconds=60)
        for ttl in [0, -1, 1.5, True]:
            with self.assertRaises(ValueError):
                self.store.issue_session(a.id, ttl_seconds=ttl)


if __name__ == '__main__':
    unittest.main()
