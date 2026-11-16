"""The legacy-read network guard must not leak into concurrent requests."""
import socket
import threading
import unittest
from contextvars import copy_context

from routers import postgres_legacy_read_fixture as fixture


class NetworkGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture._install_network_guard('localhost')

    def test_guarded_context_refuses_and_others_resolve_concurrently(self):
        started, results = threading.Event(), {}

        def guarded():
            token = fixture._offline.set(True)
            try:
                started.set()
                socket.getaddrinfo('example.invalid', 80)
            except OSError as exc:
                results['guarded'] = str(exc)
            finally:
                fixture._offline.reset(token)

        def other():
            started.wait(5)
            results['other'] = socket.getaddrinfo('localhost', 80)[0][4][0]

        threads = [threading.Thread(target=copy_context().run, args=(fn,)) for fn in (guarded, other)]
        [t.start() for t in threads]
        [t.join(10) for t in threads]
        self.assertIn('unavailable to legacy reads', results['guarded'])
        self.assertTrue(results['other'])

    def test_database_host_stays_reachable_and_guard_clears_after_reset(self):
        token = fixture._offline.set(True)
        try:
            self.assertTrue(socket.getaddrinfo('localhost', 80))
        finally:
            fixture._offline.reset(token)
        self.assertFalse(fixture._offline.get())


if __name__ == '__main__':
    unittest.main()
