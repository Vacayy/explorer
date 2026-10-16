"""홈 위젯 배치 저장: init_db 스키마 · 저장/조회 왕복 · 검증 · 404."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import database
from routers import dashboard

ITEMS = [{"i": "regime-1", "widget": "market.regime", "x": 0, "y": 0, "w": 4, "h": 3, "params": {}},
         {"i": "risk-vix", "widget": "risk.indicator", "x": 4, "y": 0, "w": 3, "h": 3,
          "params": {"key": "vix", "range": "3m"}}]


class DashboardLayoutTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'test.sqlite'
        with patch.object(database, 'DB_PATH', path):
            database.init_db()   # 실제 init_db의 DDL을 쓴다

        def connection():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            return c
        p = patch.object(dashboard, 'get_connection', connection)
        p.start()
        self.addCleanup(p.stop)
        app = FastAPI()
        app.include_router(dashboard.router)
        self.client = TestClient(app)

    def test_missing_layout_is_404_and_list_empty(self):
        self.assertEqual(self.client.get('/api/dashboard/layouts/home').status_code, 404)
        self.assertEqual(self.client.get('/api/dashboard/layouts').json(), [])

    def test_put_then_get_round_trip_and_overwrite(self):
        saved = self.client.put('/api/dashboard/layouts/home', json={"items": ITEMS})
        self.assertEqual(saved.status_code, 200)
        got = self.client.get('/api/dashboard/layouts/home').json()
        self.assertEqual(got['items'], ITEMS)
        self.assertEqual(got['name'], 'home')
        self.assertTrue(got['updated_at'])
        self.client.put('/api/dashboard/layouts/home', json={"items": ITEMS[:1]})
        self.assertEqual(self.client.get('/api/dashboard/layouts/home').json()['items'], ITEMS[:1])
        self.assertEqual([(r['name'], r['count']) for r in self.client.get('/api/dashboard/layouts').json()], [('home', 1)])

    def test_params_default_to_empty_object(self):
        item = {k: v for k, v in ITEMS[0].items() if k != 'params'}
        self.client.put('/api/dashboard/layouts/home', json={"items": [item]})
        self.assertEqual(self.client.get('/api/dashboard/layouts/home').json()['items'][0]['params'], {})

    def test_invalid_layouts_rejected_without_writing(self):
        bad = [
            [{**ITEMS[0], "x": -1}],
            [{**ITEMS[0], "w": 0}],
            [{**ITEMS[0], "h": "3"}],
            [{**ITEMS[0], "x": 1.5}],
            [{**ITEMS[0], "i": ""}],
            [{**ITEMS[0], "params": []}],
            [{k: v for k, v in ITEMS[0].items() if k != 'widget'}],
            [{**ITEMS[0], "extra": 1}],
            [ITEMS[0], {**ITEMS[1], "i": ITEMS[0]["i"]}],   # 인스턴스 id 중복
        ]
        for items in bad:
            with self.subTest(items=items):
                self.assertEqual(self.client.put('/api/dashboard/layouts/home', json={"items": items}).status_code, 422)
        self.assertEqual(self.client.put('/api/dashboard/layouts/home', json=ITEMS).status_code, 422)   # 본문은 {items}
        self.assertEqual(self.client.put('/api/dashboard/layouts/Bad%20Name', json={"items": ITEMS}).status_code, 422)
        self.assertEqual(self.client.get('/api/dashboard/layouts/home').status_code, 404)


if __name__ == '__main__':
    unittest.main()
