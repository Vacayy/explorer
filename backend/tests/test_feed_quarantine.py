import json
import http.server
import socket
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import requests

from pipeline.base import RawDoc, SourceRef
from pipeline.feed_backlog import FeedBacklog, fetch_pending_reference
from pipeline.feed_quarantine import SourceQuarantined, blocked_host, blocked_ref, guard_network, load_hosts


class FeedQuarantineTest(unittest.TestCase):
    def test_requests_redirect_is_stopped_before_the_blocked_host(self):
        class Redirect(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header('Location', 'http://blocked.example/path')
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(('127.0.0.1', 0), Redirect)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with guard_network({'blocked.example'}), self.assertRaises(SourceQuarantined):
                requests.get(f'http://127.0.0.1:{server.server_port}/', timeout=3)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_network_guards_stop_blocked_destinations_and_curl_redirects(self):
        old_resolve = socket.getaddrinfo
        with patch('subprocess.run') as run:
            with guard_network({'blocked.example'}):
                with self.assertRaises(SourceQuarantined):
                    socket.getaddrinfo('sub.blocked.example', 443)
                with self.assertRaises(SourceQuarantined):
                    urllib.request.urlopen('https://blocked.example/path')
                with self.assertRaises(SourceQuarantined):
                    requests.get('https://blocked.example/path')
                with self.assertRaises(SourceQuarantined):
                    subprocess.run(['curl', '-sL', '--max-time', '15', '-A', 'ua', 'https://blocked.example/'])
                run.assert_not_called()
                subprocess.run(['curl', '-sL', '--max-time', '15', '-A', 'ua', 'https://allowed.example/'])
                self.assertEqual(run.call_args.args[0][1], '-s')
        self.assertIs(socket.getaddrinfo, old_resolve)

    def test_quarantined_refs_are_retained_and_other_lanes_run(self):
        class Connector:
            def fetch(self, ref):
                return [RawDoc('telegram', 'synthetic')]
        with tempfile.TemporaryDirectory() as directory:
            queue = FeedBacklog(Path(directory) / 'queue.sqlite')
            hosts = frozenset({'blocked.example'})
            queue.enqueue_ref('blog', 'blocked', SourceRef('one', {'url': 'https://blocked.example/post'}))
            queue.enqueue_ref('blog', 'blocked', SourceRef('two', {'url': 'https://sub.blocked.example/post'}))
            queue.enqueue_ref('telegram', 'channel', SourceRef('page', {'url': 'https://blocked.example/link'}))
            skip = lambda name, ref: name == 'blog' and blocked_ref(ref, hosts)
            self.assertEqual(fetch_pending_reference(queue, {'blog': Connector(), 'telegram': Connector()}, skip=skip), 1)
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending_refs').fetchone()[0], 2)
            self.assertIsNone(queue.next_pending_ref(skip=skip))
            self.assertEqual(queue.conn.execute('SELECT count(*) FROM pending_refs').fetchone()[0], 2)
            queue.close()

    def test_private_file_and_host_matching(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'hosts.json'
            self.assertFalse(load_hosts(path))
            path.write_text(json.dumps(['blocked.example']))
            path.chmod(0o600)
            hosts = load_hosts(path)
            self.assertTrue(blocked_host('sub.blocked.example.', hosts))
            self.assertFalse(blocked_host('notblocked.example', hosts))
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                load_hosts(path)
