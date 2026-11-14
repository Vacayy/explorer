import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import peers


class PeerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.now = datetime(2026, 11, 1, 23, tzinfo=ZoneInfo('Asia/Seoul'))
        prices = json.loads((peers.DATA / 'peer-prices.json').read_text())
        catalog = json.loads((peers.DATA / 'peer-catalog.json').read_text())
        catalog['companies'] = [c for c in catalog['companies'] if c['code'] in prices['prices']]
        self.published = dict(catalog=catalog, prices=prices, publishedAt='2026-11-01T22:00:00+09:00', baselineOn='2026-11-01')

    def test_seed_is_explicit_when_no_collection(self):
        result = peers.read_runtime(self.root, now=self.now)
        self.assertEqual(result.origin, 'seed')
        self.assertEqual(result.signalStatus, 'held')
        self.assertIsNone(result.lastAttempt)
        self.assertEqual(result.priceAgeDays, 2)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_current_bundle_is_consistent_and_error_keeps_data(self):
        (self.root / 'current.json').write_text(json.dumps(self.published))
        (self.root / 'last-attempt.json').write_text(json.dumps(dict(at='2026-11-02T21:00:00+09:00', status='error', error='provider unavailable')))
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        result = peers.read_runtime(self.root, now=self.now)
        self.assertEqual(result.origin, 'collector')
        self.assertEqual(result.lastAttempt.status, 'error')
        self.assertEqual(len(result.catalog.companies), len(result.prices.prices))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_corrupt_file_is_503_not_seed_fallback(self):
        (self.root / 'current.json').write_text('{corrupt')
        app = FastAPI()
        app.include_router(peers.router)
        with patch.object(peers, 'ROOT', self.root):
            response = TestClient(app).get('/api/peers/runtime')
        self.assertEqual(response.status_code, 503)

    def test_invalid_series_and_mismatched_members_fail_validation(self):
        self.published['prices']['dates'].reverse()
        (self.root / 'current.json').write_text(json.dumps(self.published))
        with self.assertRaises(ValueError):
            peers.read_runtime(self.root, now=self.now)
        self.published['prices']['dates'].reverse()
        self.published['prices']['prices'].pop(next(iter(self.published['prices']['prices'])))
        (self.root / 'current.json').write_text(json.dumps(self.published))
        with self.assertRaises(ValueError):
            peers.read_runtime(self.root, now=self.now)
