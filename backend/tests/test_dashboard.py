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

    def test_presets_crud_keeps_params(self):
        """내 프리셋 — 지금 배치를 이름 붙여 저장·불러오기·덮어쓰기·이름 바꾸기·삭제, 위젯 params(종목 추적)도 그대로"""
        items = ITEMS + [{"i": "track.stock#0", "widget": "track.stock", "x": 0, "y": 3, "w": 6, "h": 8, "params": {"code": "144960", "name": "뉴파워프라즈마"}}]
        made = self.client.post('/api/dashboard/presets', json={"label": "종목 추적", "items": items})
        self.assertEqual(made.status_code, 200)
        pid = made.json()["id"]
        got = self.client.get('/api/dashboard/presets').json()
        self.assertEqual([p["label"] for p in got], ["종목 추적"])
        self.assertEqual(got[0]["items"][-1]["params"]["code"], "144960")
        self.client.patch(f'/api/dashboard/presets/{pid}', json={"label": "아침 점검", "items": ITEMS})
        got = self.client.get('/api/dashboard/presets').json()[0]
        self.assertEqual((got["label"], len(got["items"])), ("아침 점검", 2))
        self.assertEqual(self.client.post('/api/dashboard/presets', json={"label": "", "items": ITEMS}).status_code, 422)
        self.client.delete(f'/api/dashboard/presets/{pid}')
        self.assertEqual(self.client.get('/api/dashboard/presets').json(), [])

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
