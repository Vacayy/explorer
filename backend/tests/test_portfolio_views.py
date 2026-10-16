"""포트폴리오 읽기 전용 조회 — 알림 이력·원칙 현재 상태·묶음 1D 요약 (portfolio-ledger §알림 이력, portfolio-intelligence §5). 값은 가상."""
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import portfolio as pf
from pipeline import portfolio_alerts as pa
from pipeline import portfolio_principles as pp
from tests.test_portfolio_principles import summary


def alerts_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(pa.SCHEMA + "CREATE TABLE companies (stock_code TEXT PRIMARY KEY, corp_name TEXT); INSERT INTO companies VALUES ('AAAAAA', '가나');")
    return conn


class AlertHistoryTests(unittest.TestCase):
    def test_keys_become_type_stock_band_and_kst_time(self):
        conn = alerts_db()
        conn.executemany("INSERT INTO portfolio_alerts_sent (key, sent_at) VALUES (?, datetime('now', ?))", [
            ("day:2026-01-06:AAAAAA:-1", "-1 hours"), ("avg:AAAAAA:2026-01-01:2", "-2 hours"),
            ("tech:AAAAAA:2026-01-05:high_52w", "-3 hours"), ("disc:20260105000123", "-4 hours"),
            ("summary:2026-01-05", "-5 hours"), ("day:2025-01-01:AAAAAA:1", "-40 days")])
        items = pa.history(conn, days=14)
        self.assertEqual([i["kind"] for i in items], ["day", "avg", "tech", "disc", "summary"])   # 최신 먼저, 14일 밖 제외
        self.assertEqual(items[0]["label"], "전일 대비 −5%p 이하")
        self.assertEqual(items[1]["label"], "평단 대비 +20%p 이상")
        self.assertEqual((items[0]["code"], items[0]["name"]), ("AAAAAA", "가나"))
        self.assertIn("rcpNo=20260105000123", items[3]["url"])
        self.assertRegex(items[0]["sent_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertEqual(set(items[0]), {"kind", "label", "code", "name", "date", "sent_at", "url"})   # 금액·수량 필드 없음

    def test_missing_table_is_empty(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.assertEqual(pa.history(conn), [])


class PrincipleStateTests(unittest.TestCase):
    def test_current_violations_mark_which_were_alerted(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        pp.ensure_schema(conn)
        pid = pp.add(conn, "가상 원칙", [{"type": "max_weight", "params": {"pct": 30}}, {"type": "min_cash", "params": {"pct": 20}}])
        conn.execute("INSERT INTO portfolio_principle_state (key, since) VALUES (?, '2026-01-05 01:00:00')", (f"{pid}:0:AAAAAA",))
        state = pp.current(conn, summary(weight=40, cash=10), today="2026-01-10")
        self.assertEqual(state["rules"], 2)
        by = {v["key"]: v for v in state["items"]}
        self.assertEqual(by[f"{pid}:0:AAAAAA"]["alerted_since"], "2026-01-05 01:00:00")
        self.assertIsNone(by[f"{pid}:1:cash"]["alerted_since"])          # 아직 알림 전(다음 점검에서 보냄)
        self.assertNotIn("principle", by[f"{pid}:1:cash"])                # 원문은 원칙 카드에서만

    def test_no_principles(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.assertEqual(pp.current(conn, summary()), {"rules": 0, "items": []})


class RouteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "pf.sqlite"
        conn = self.connect()
        from pipeline.watch_rules import SCHEMA as WATCH_SCHEMA
        conn.executescript(WATCH_SCHEMA + pf.SCHEMA + pa.SCHEMA + """
            CREATE TABLE companies (stock_code TEXT PRIMARY KEY, corp_name TEXT);
            CREATE TABLE stock_prices (stock_code TEXT, trade_date TEXT, close REAL);
            INSERT INTO companies VALUES ('AAAAAA', '가나');
            INSERT INTO portfolio_alerts_sent (key) VALUES ('day:2026-01-06:AAAAAA:1');""")
        conn.commit()
        conn.close()
        from routers import portfolio as route
        app = FastAPI()
        app.include_router(route.router)
        self.client = TestClient(app)
        patcher = mock.patch.object(pf, "connect", self.connect)
        patcher.start()
        self.addCleanup(patcher.stop)

    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def test_alerts_and_principle_state_are_reads(self):
        r = self.client.get("/api/portfolio/alerts")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([(i["kind"], i["name"]) for i in r.json()], [("day", "가나")])
        s = self.client.get("/api/portfolio/principles/state")
        self.assertEqual(s.status_code, 200, s.text)
        self.assertEqual((s.json()["rules"], s.json()["items"]), (0, []))


class GroupDigestTests(unittest.TestCase):
    def test_latest_1d_digest_per_member_without_generation(self):
        from pipeline import watch_rules as wr
        from routers.spine_groups import router
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "g.sqlite"

        def connect():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            return c
        conn = connect()
        today = date.today()
        conn.executescript("""
            CREATE TABLE companies(corp_code TEXT, corp_name TEXT, stock_code TEXT, market TEXT, sector TEXT);
            CREATE TABLE stock_prices(stock_code TEXT, trade_date TEXT, close REAL, market_cap INTEGER);
            CREATE TABLE watchlist(id INTEGER PRIMARY KEY, stock_code TEXT UNIQUE, corp_code TEXT, corp_name TEXT, conviction INTEGER, target_price INTEGER, thesis TEXT);
            CREATE TABLE entities(id INTEGER PRIMARY KEY, type TEXT, name TEXT, aliases TEXT);
            CREATE TABLE entity_digests(id INTEGER PRIMARY KEY, entity_id INTEGER, period TEXT, period_start TEXT, digest TEXT, insights TEXT, doc_count INTEGER);
        """ + wr.SCHEMA)
        conn.executemany("INSERT INTO companies VALUES (?,?,?,?,?)", [("c1", "가나", "000001", "KOSPI", "IT"), ("c2", "다라", "000002", "KOSDAQ", "BIO")])
        conn.executemany("INSERT INTO entities VALUES (?,?,?,?)", [(1, "company", "가나", "000001"), (2, "company", "다라", "000002")])
        conn.executemany("INSERT INTO entity_digests (entity_id, period, period_start, digest, insights, doc_count) VALUES (?,?,?,?,?,?)", [
            (1, "1d", (today - timedelta(days=2)).isoformat(), "# 옛 요약", None, 2),
            (1, "1d", (today - timedelta(days=1)).isoformat(), "- 새 요약 첫 줄\n- 둘째", "새로운 점", 5),
            (2, "1d", (today - timedelta(days=30)).isoformat(), "너무 오래됨", None, 1)])
        conn.commit()
        conn.close()
        with mock.patch.object(wr, "connect", connect):
            app = FastAPI()
            app.include_router(router)
            client = TestClient(app)
            gid = client.post("/api/spine/groups", json={"name": "테스트", "kind": "watch"}).json()["id"]
            for code in ("000001", "000002"):
                client.post(f"/api/spine/groups/{gid}/members", json={"stock_code": code})
            r = client.get(f"/api/spine/groups/{gid}/digests")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["as_of"], (today - timedelta(days=1)).isoformat())
        self.assertEqual([(i["code"], i["name"], i["lead"], i["insights"]) for i in body["items"]], [("000001", "가나", "새 요약 첫 줄", "새로운 점")])


if __name__ == "__main__":
    unittest.main()
