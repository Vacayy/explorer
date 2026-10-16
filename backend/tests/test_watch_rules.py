"""종목 묶음·감시 규칙: 규칙 덮어쓰기, 멱등 평가, pass 전이 신호, 레거시 이관 (D-185)."""
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import watch_rules as wr
from routers.spine_groups import router

BASE = """
CREATE TABLE companies(corp_code TEXT, corp_name TEXT, stock_code TEXT, market TEXT, sector TEXT);
CREATE TABLE stock_prices(id INTEGER PRIMARY KEY, stock_code TEXT, trade_date TEXT, open INTEGER, high INTEGER, low INTEGER,
 close INTEGER, volume INTEGER, market_cap INTEGER, shares INTEGER, UNIQUE(stock_code, trade_date));
CREATE TABLE watchlist(id INTEGER PRIMARY KEY, stock_code TEXT UNIQUE, corp_code TEXT, corp_name TEXT, conviction INTEGER,
 target_price INTEGER, thesis TEXT);
"""


def sessions(n: int) -> list[str]:
    day, out = date(2026, 6, 1), []
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


class WatchRulesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "explorer.sqlite"
        conn = self.connect()
        conn.executescript(BASE + wr.SCHEMA)
        conn.executemany("INSERT INTO companies VALUES (?,?,?,?,?)", [("c1", "가나", "000001", "KOSPI", "IT"), ("c2", "다라", "000002", "KOSDAQ", "BIO")])
        self.days = sessions(30)
        rows = []
        for code in ("000001", "000002"):
            for i, day in enumerate(self.days):
                high = 200 if (code == "000001" and i == len(self.days) - 1) else 100
                rows.append((code, day, 95, high, 90, 98, 1000 + i, 10_000, 100))
        conn.executemany("INSERT INTO stock_prices (stock_code, trade_date, open, high, low, close, volume, market_cap, shares) VALUES (?,?,?,?,?,?,?,?,?)", rows)
        conn.executemany("INSERT INTO watchlist (stock_code, corp_code, corp_name, conviction, target_price, thesis) VALUES (?,?,?,?,?,?)",
                         [("000001", "c1", "가나", 4, 150, "논지 A"), ("000002", "c2", "다라", 2, None, None)])
        conn.commit()
        conn.close()
        patcher = patch.object(wr, "connect", self.connect)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def group_with_rules(self):
        group = self.client.post("/api/spine/groups", json={"name": "테스트", "kind": "watch"}).json()
        for code in ("000001", "000002"):
            self.assertEqual(self.client.post(f"/api/spine/groups/{group['id']}/members", json={"stock_code": code}).status_code, 201)
        put = self.client.put(f"/api/spine/groups/{group['id']}/rules", json={
            "default": [{"strategy_id": "high_5d"}],
            "members": {"000001": [{"strategy_id": "volume_increase"}]}})
        self.assertEqual(put.status_code, 200, put.text)
        return put.json()

    def test_member_rules_add_to_and_override_defaults(self):
        detail = self.group_with_rules()
        conn = self.connect()
        codes = sorted(r["strategy_id"] for r in wr.effective_rules(conn, detail["id"], "000001"))
        self.assertEqual(codes, ["high_5d", "volume_increase"])
        self.assertEqual([r["strategy_id"] for r in wr.effective_rules(conn, detail["id"], "000002")], ["high_5d"])
        kept = detail["rules"]["default"][0]["id"]
        override = self.client.put(f"/api/spine/groups/{detail['id']}/rules", json={
            "default": [{"strategy_id": "high_5d"}], "members": {"000001": [{"strategy_id": "high_5d", "params": {"period": 10}}]}}).json()
        self.assertEqual(override["rules"]["default"][0]["id"], kept, "unchanged rules keep their id so history survives")
        effective = wr.effective_rules(conn, detail["id"], "000001")
        self.assertEqual(len(effective), 1)
        self.assertEqual(wr.rule_condition(effective[0])["params"]["period"], 10)
        conn.close()

    def test_invalid_and_ranking_rules_are_rejected(self):
        group = self.client.post("/api/spine/groups", json={"name": "x"}).json()
        bad = self.client.put(f"/api/spine/groups/{group['id']}/rules", json={"default": [{"strategy_id": "nope"}]})
        self.assertEqual(bad.status_code, 400)
        rank = self.client.put(f"/api/spine/groups/{group['id']}/rules", json={"default": [{"strategy_id": "rank_volume"}]})
        self.assertEqual(rank.status_code, 400)

    def test_evaluation_is_idempotent_and_signals_are_pass_transitions(self):
        detail = self.group_with_rules()
        gid = detail["id"]
        previous, latest = self.days[-2], self.days[-1]
        first = self.client.post(f"/api/spine/groups/{gid}/evaluate", params={"as_of": previous}).json()["summary"]
        self.assertEqual((first["evaluated"], first["skipped"]), (3, 0))
        again = self.client.post(f"/api/spine/groups/{gid}/evaluate", params={"as_of": previous}).json()["summary"]
        self.assertEqual((again["evaluated"], again["skipped"]), (0, 3))
        forced = self.client.post(f"/api/spine/groups/{gid}/evaluate", params={"as_of": previous, "force": "true"}).json()["summary"]
        self.assertEqual(forced["evaluated"], 3)
        today = self.client.post(f"/api/spine/groups/{gid}/evaluate").json()
        self.assertEqual(today["summary"]["as_of"], latest)
        evaluations = self.client.get(f"/api/spine/groups/{gid}/evaluations").json()
        self.assertEqual(evaluations["as_of"], latest)
        self.assertTrue({e["status"] for e in evaluations["items"]} <= {"pass", "fail", "unavailable"})
        signals = self.client.get(f"/api/spine/groups/{gid}/signals").json()["items"]
        high = [s for s in signals if s["strategy_id"] == "high_5d"]
        self.assertEqual([(s["stock_code"], s["as_of"]) for s in high], [("000001", latest)], "only the new 5-day high on the last day is a transition")
        self.assertEqual(high[0]["name"], "가나")
        member = next(m for m in today["group"]["members"] if m["stock_code"] == "000001")
        self.assertIn("high_5d", [s["strategy_id"] for s in member["signals"]])
        self.assertEqual(member["rule_count"], 2)
        listing = self.client.get("/api/spine/groups").json()
        self.assertEqual(listing["items"][0]["last_as_of"], latest)
        self.assertGreaterEqual(listing["items"][0]["today_signals"], 1)

    def test_legacy_watchlist_migration_dry_run_writes_nothing_then_apply_is_idempotent(self):
        conn = self.connect()
        plan = wr.migrate_watchlist(conn, dry_run=True)
        self.assertTrue(plan["create_group"])
        self.assertEqual([i["stock_code"] for i in plan["add"]], ["000001", "000002"])
        self.assertIsNone(wr.default_watch_group_id(conn, create=False), "dry-run must not create the group")
        self.assertEqual(conn.execute("SELECT COUNT(*) n FROM stock_group_members").fetchone()["n"], 0)
        first = wr.migrate_watchlist(conn)
        self.assertEqual(len(first["add"]), 2)
        second = wr.migrate_watchlist(conn)
        self.assertEqual((second["group_id"], second["add"], second["fill"]), (first["group_id"], [], []))
        self.assertEqual(len(second["same"]), 2)
        member = conn.execute("SELECT conviction, target_price, thesis FROM stock_group_members WHERE group_id=? AND stock_code='000001'",
                              (first["group_id"],)).fetchone()
        self.assertEqual(tuple(member), (4, 150, "논지 A"))
        self.assertEqual(conn.execute("SELECT COUNT(*) n FROM watchlist").fetchone()["n"], 2, "legacy table is kept")
        conn.close()

    def test_migration_fills_only_empty_member_fields(self):
        conn = self.connect()
        gid = wr.default_watch_group_id(conn)
        conn.execute("INSERT INTO stock_group_members (group_id, stock_code, conviction, thesis) VALUES (?, '000001', 5, NULL)", (gid,))
        conn.execute("INSERT INTO stock_group_members (group_id, stock_code) VALUES (?, '000002')", (gid,))
        conn.commit()
        plan = wr.migrate_watchlist(conn)
        self.assertEqual(plan["add"], [])
        self.assertEqual([(i["stock_code"], i["fields"]) for i in plan["fill"]], [("000001", ["target_price", "thesis"]), ("000002", ["conviction"])])
        row = conn.execute("SELECT conviction, target_price, thesis FROM stock_group_members WHERE stock_code='000001'").fetchone()
        self.assertEqual(tuple(row), (5, 150, "논지 A"), "group value wins, empty cells take legacy values")
        conn.close()

    def test_watched_is_union_of_watch_groups_and_thesis_prefers_filled_member(self):
        conn = self.connect()
        default = wr.default_watch_group_id(conn)
        self.assertEqual(wr.default_watch_group_id(conn), default, "get-or-create is idempotent")
        other = conn.execute("INSERT INTO stock_groups (name, kind) VALUES ('반도체', 'watch')").lastrowid
        held = conn.execute("INSERT INTO stock_groups (name, kind) VALUES ('보유', 'portfolio')").lastrowid
        conn.executemany("INSERT INTO stock_group_members (group_id, stock_code, thesis) VALUES (?,?,?)",
                         [(default, "000001", None), (other, "000001", "다른 묶음 논지"), (other, "000002", None), (held, "000003", "보유")])
        conn.commit()
        self.assertEqual(wr.watched(conn), {"000001": "가나", "000002": "다라"}, "portfolio members are not watched")
        self.assertEqual(wr.watch_thesis(conn, "000001")["thesis"], "다른 묶음 논지")
        conn.execute("UPDATE stock_group_members SET thesis='기본 논지' WHERE group_id=? AND stock_code='000001'", (default,))
        self.assertEqual(wr.watch_thesis(conn, "000001")["thesis"], "기본 논지")
        self.assertIsNone(wr.watch_thesis(conn, "000003"))
        conn.close()

    def test_default_watch_endpoint_creates_once_and_lists_members(self):
        first = self.client.get("/api/spine/groups/default-watch").json()
        self.assertEqual((first["name"], first["kind"], first["members"]), (wr.DEFAULT_WATCH_GROUP_NAME, "watch", []))
        self.client.post(f"/api/spine/groups/{first['id']}/members", json={"stock_code": "000001"})
        again = self.client.get("/api/spine/groups/default-watch").json()
        self.assertEqual(again["id"], first["id"])
        self.assertEqual([m["name"] for m in again["members"]], ["가나"])

    def test_portfolio_members_take_no_amounts_and_expose_none(self):
        """D-212: 수량·매수가는 거래 원장에만 — 묶음 API는 받지도 돌려주지도 않는다."""
        group = self.client.post("/api/spine/groups", json={"name": "보유", "kind": "portfolio"}).json()
        rejected = self.client.post(f"/api/spine/groups/{group['id']}/members", json={"stock_code": "000001", "quantity": 10, "avg_price": 70})
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(self.client.patch(f"/api/spine/groups/{group['id']}/members/000001", json={"avg_price": 70}).status_code, 422)
        detail = self.client.post(f"/api/spine/groups/{group['id']}/members", json={"stock_code": "000001"}).json()
        member = detail["members"][0]
        self.assertEqual(member["close"], 98)
        self.assertTrue({"pnl", "return_pct", "quantity", "avg_price"}.isdisjoint(member))
        removed = self.client.delete(f"/api/spine/groups/{group['id']}/members/000001").json()
        self.assertEqual(removed["members"], [])
        self.assertEqual(self.client.delete(f"/api/spine/groups/{group['id']}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/spine/groups/{group['id']}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
