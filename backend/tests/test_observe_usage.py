"""사용 집계 — IA 위치(section·tab)별 방문·머문 시간, 옛 주소와 '안 연 화면' 분리, 생성 대비 열람 (docs/specs/observability.md)."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import database
from pipeline import observe


def _ts(days_ago: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch.object(database, "DB_PATH", Path(self.tmp.name) / "t.db").start()
        self.addCleanup(patch.stopall)
        database.init_db()

    def _save(self, *events):
        observe.save_events([{"ts": _ts(), "session": "s", **e} for e in events])

    def _usage(self):
        conn = database.get_connection()
        try:
            return observe.usage(conn, 7), observe.value(conn, 7)
        finally:
            conn.close()

    def test_sections_group_visits_and_dwell_by_tab(self):
        self._save(
            {"type": "view", "name": "/industry/:sector", "section": "industry", "tab": "sectors"},
            {"type": "leave", "name": "/industry/:sector", "section": "industry", "tab": "sectors", "dwell_ms": 60_000},
            {"type": "action", "name": "peer.group", "section": "industry", "tab": "sectors", "entity": "HBM"},
            {"type": "view", "name": "/follow/trade", "section": "industry", "tab": "trade"},
            {"type": "leave", "name": "/follow/trade", "section": "industry", "tab": "trade", "dwell_ms": 20_000},
            {"type": "view", "name": "/home", "section": "home", "tab": "dashboard"},
            {"type": "view", "name": "/discover/peers"},   # 개편 전 기록(IA 위치 없음)
        )
        u, _ = self._usage()
        names = [s["section"] for s in u["sections"]]
        self.assertEqual(names, ["industry", "home", None])   # 개편 전 기록은 맨 아래
        ind = u["sections"][0]
        self.assertEqual((ind["visits"], ind["actions"], ind["avg_dwell_ms"]), (2, 1, 40_000))
        self.assertEqual([(t["tab"], t["visits"], t["avg_dwell_ms"]) for t in ind["tabs"]], [("sectors", 1, 60_000), ("trade", 1, 20_000)])

    def test_old_routes_are_not_dropped_screens(self):
        conn = database.get_connection()
        conn.executemany("INSERT INTO usage_events (ts, session, type, name, ref) VALUES (?,?,?,?,?)", [
            (_ts(20), "s", "view", "/discover/peers?group", None),     # 지난달엔 열었고 이번 주 안 연 옛 주소
            (_ts(20), "s", "view", "/value-chain", None),              # 지난달엔 열었고 이번 주 안 연 현행 화면
            (_ts(1), "s", "view", "/home/b/:boardId", "/home"),
            (_ts(1), "s", "view", "/home/b/:boardId", "/home"),
            (_ts(1), "s", "view", "/home?home_view=feed", None),
        ])
        conn.execute("INSERT INTO api_requests_hourly (hour, method, route, status_class, count) VALUES (?,?,?,?,?)",
                     (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:00"), "GET", "/api/dashboard/boards", "2xx", 5))
        conn.commit()
        conn.close()
        u, _ = self._usage()
        self.assertEqual(u["dropped"], ["/value-chain"])
        self.assertEqual([(o["name"], o["n"], o["refs"]) for o in u["old_routes"]],
                         [("/home/b/:boardId", 2, ["/home"]), ("/home?home_view=feed", 1, [])])
        self.assertEqual(u["boards_api_calls"], 5)

    def test_is_old_route(self):
        for name in ["/home/b/:boardId", "/company/:stockCode/financials", "/analyze/:stockCode/valuation", "/discover/peers?view=performance&group",
                     "/home?home_view=feed", "/follow/transcripts?view=proxies", "/regimes", "/us"]:
            self.assertTrue(observe.is_old_route(name), name)
        for name in ["/home", "/home/us", "/follow/transcripts?view=season", "/follow/transcripts?t", "/retail", "/follow/stocks",
                     "/analyze/:stockCode/summary", "/us/:ticker", "/industry/:sector", "/person/:id"]:
            self.assertFalse(observe.is_old_route(name), name)

    def test_open_rates(self):
        conn = database.get_connection()
        conn.execute("INSERT INTO us_briefings (trade_date, signature, synthesis_json) VALUES ('2026-11-05', 'x', '{}')")
        conn.execute("INSERT INTO us_briefings (trade_date, signature, synthesis_json) VALUES ('2026-11-04', 'y', '{}')")
        conn.commit()
        conn.close()
        self._save(
            {"type": "open", "name": "overnight.full", "entity": "2026-11-05"},
            {"type": "open", "name": "overnight.full", "entity": "2026-11-05"},
            {"type": "open", "name": "transcript.stage", "entity": "call", "ref": "7"},
            {"type": "open", "name": "transcript.stage", "entity": "reaction", "ref": "7"},
            {"type": "open", "name": "transcript.stage", "entity": "before", "ref": "8"},
            {"type": "open", "name": "ai_outputs.click", "entity": "narrative:3"},
        )
        _, v = self._usage()
        rates = {r["key"]: (r["generated"], r["opened"]) for r in v["rates"]}
        self.assertEqual(rates["overnight"], (2, 1))
        self.assertEqual(rates["call"][1], 1)       # 같은 콜 두 단계 = 1, '발표 전'은 생성물이 아니다
        self.assertEqual(rates["ai_outputs"][1], 1)

    def test_summary_matches_response_model(self):
        from models.observe import ObserveSummary
        self._save({"type": "view", "name": "/home", "section": "home", "tab": "dashboard"})
        ObserveSummary.model_validate(observe.summary(7))


if __name__ == "__main__":
    unittest.main()
