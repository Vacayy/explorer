"""요청 집계 저장(observe.flush)이 이벤트 루프를 막지 않는다 (API 성능 A단계 ②).

- 저장은 미들웨어가 루프 밖 스레드에서 한다 — 저장이 오래 걸려도 요청 응답은 바로 나간다.
- 저장 주기 표시는 한 번만 준다(동시에 끝난 요청이 저장을 겹쳐 예약하지 않게).
- DB 쓰기 잠금이 걸려 있으면 짧게 기다리고 넘긴다. 버퍼는 되돌려 다음 저장에 더한다(유실 없음).
"""
import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

import database
from main import app
from pipeline import observe


class FlushTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch.object(database, "DB_PATH", Path(self.tmp.name) / "t.db").start()
        self.addCleanup(patch.stopall)
        database.init_db()
        patch.object(observe, "_buf", {}).start()

    def _rows(self):
        conn = database.get_connection()
        try:
            return [dict(r) for r in conn.execute("SELECT route, count, max_ms FROM api_requests_hourly ORDER BY route")]
        finally:
            conn.close()

    def test_claim_flush_once_per_period(self):
        patch.object(observe, "_last_flush", time.monotonic() - observe.FLUSH_SECONDS - 1).start()
        self.assertTrue(observe.claim_flush())
        self.assertFalse(observe.claim_flush())

    def test_record_request_does_not_write(self):
        patch.object(observe, "_last_flush", time.monotonic() - observe.FLUSH_SECONDS - 1).start()
        observe.record_request("GET", "/api/x", 200, 50)
        self.assertEqual(self._rows(), [])
        self.assertEqual(observe.flush(), 1)
        self.assertEqual(self._rows(), [{"route": "/api/x", "count": 1, "max_ms": 50.0}])

    def test_locked_db_gives_up_quickly_and_keeps_buffer(self):
        observe.record_request("GET", "/api/x", 200, 50)
        observe.record_request("GET", "/api/x", 200, 70)
        locker = database.get_connection()
        locker.execute("BEGIN IMMEDIATE")
        try:
            t = time.perf_counter()
            self.assertEqual(observe.flush(busy_timeout_ms=200), 0)
            self.assertLess(time.perf_counter() - t, 2)
        finally:
            locker.rollback()
            locker.close()
        observe.record_request("GET", "/api/x", 200, 30)
        self.assertEqual(observe.flush(), 1)
        self.assertEqual(self._rows(), [{"route": "/api/x", "count": 3, "max_ms": 70.0}])


class MiddlewareTests(unittest.TestCase):
    def test_flush_runs_off_the_event_loop(self):
        calls = []
        done = threading.Event()

        def slow_flush(busy_timeout_ms=None):
            calls.append(busy_timeout_ms)
            time.sleep(1.5)
            done.set()
            return 0
        with patch.object(observe, "flush", slow_flush), \
                patch.object(observe, "_last_flush", time.monotonic() - observe.FLUSH_SECONDS - 1):
            async def call():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as ac:
                    t = time.perf_counter()
                    r = await ac.get("/api/health")
                    return r.status_code, time.perf_counter() - t
            status, elapsed = asyncio.run(call())   # 루프 종료가 스레드를 기다리므로 경과는 요청 안에서만 잰다
            self.assertEqual(status, 200)
            self.assertLess(elapsed, 1.0)
            self.assertTrue(done.wait(5))
        self.assertEqual(calls, [observe.FLUSH_BUSY_TIMEOUT_MS])


if __name__ == "__main__":
    unittest.main()
