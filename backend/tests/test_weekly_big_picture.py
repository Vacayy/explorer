"""이번 주 큰 그림 (ia-redesign §4.25, D-313 4) — LLM은 전부 대역.

- 입력 해시가 같으면 LLM 없이 건너뛴다.
- 검증: 입력에 없던 서사·근거 id, 허용 밖 상태, 원문에 없는 인용은 버린다. 근거는 id만 저장한다.
- 이벤트: 지난 생성 뒤 새 버전 3편 이상 + 그날 생성 시도 없음. 수동: 6시간 쿨다운. 공통: 주 6회 한도.
- GET: 생성분이 없으면 메가 기반(source='mega'), 있으면 줄기·전제(근거 문장은 읽을 때 원천에서).
"""
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import database
from pipeline import weekly_big_picture as wbp
from routers import spine_world

ROOT = Path(__file__).resolve().parents[2]

SEED = """
INSERT INTO narratives(id, topic, version, title, body, created_at, kind) VALUES
  (1, '메모리', 10, '메모리 부족은 2028년까지 길어집니다', '## 3줄 요약\n- 장기계약이 이익을 묶었습니다.\n- 가격 인상이 번집니다.', datetime('now', '-9 days'), 'topic'),
  (2, '메모리', 11, '메모리 가격 인상이 2위권 업체로 번집니다', '## 3줄 요약\n- 2위권 업체가 가격을 올렸습니다.\n- 삼성 실적이 확인했습니다.', datetime('now', '-2 days'), 'topic'),
  (3, '정치', 1, '민주당이 상원 장악을 확정했습니다', '## 3줄 요약\n- 아이오와까지 이겼습니다.', datetime('now', '-1 days'), 'topic'),
  (4, '주주환원', 8, '역대급 이익에도 주가는 따라오지 못했습니다', '## 3줄 요약\n- 실적과 주가의 괴리가 커졌습니다.', datetime('now', '-2 days'), 'topic'),
  (5, 'AI', 34, '소비자 에이전트가 추론 수요를 키웁니다', '## 3줄 요약\n- 전력이 속도를 정합니다.', datetime('now', '-10 days'), 'topic');
UPDATE narratives SET superseded_at = datetime('now', '-2 days') WHERE id = 1;
INSERT INTO us_briefings(trade_date, signature, synthesis_json, created_at) VALUES
  (date('now', '-1 days'), 's', '{"key_points": ["AI 수익성 우려로 반도체지수가 3.4% 하락했다", "유가가 급락했다"]}', datetime('now', '-1 days'));
"""


def _mt(conn, mt_id, days_ago, slot, items):
    conn.execute("INSERT INTO market_today (id, trade_date, slot, window_start, window_end, items_json, sources_json, doc_count, created_at) "
                 "VALUES (?, date('now', ?), ?, 'a', 'b', ?, '{}', 10, datetime('now', ?))",
                 (mt_id, f"-{days_ago} days", slot, json.dumps(items, ensure_ascii=False), f"-{days_ago} days"))


def good_output(m=None):
    return {"strands": [
        {"title": "메모리 부족이 2위권으로 번지고 있습니다", "status": "strengthening", "narratives": [2, 999],
         "evidence": ["mt:1:0", "ov:" + (m["overnight_days"][0]["trade_date"] if m else "x") + ":0", "mt:77:0"]},
        {"title": "정치 변수가 새로 들어왔습니다", "status": "새로", "narratives": [3], "evidence": []},
        {"title": "상태가 이상한 줄기", "status": "fine", "narratives": [4], "evidence": []},
        {"title": "서사 없는 줄기", "status": "mixed", "narratives": [12345], "evidence": []},
        {"title": "AI 수요는 전력이 정합니다", "status": "mixed", "narratives": [5], "evidence": ["mt:1:1"]},
    ], "premises": {
        "settled": [{"text": "장기계약이 메모리 이익을 묶었습니다."}],
        "contested": [{"text": "주주환원이 하단을 받친다는 믿음이 흔들렸습니다.",
                       "shaken_by": {"narrative_id": 4, "quote": "역대급 이익에도 주가는 따라오지 못했습니다"}},
                      {"text": "가짜 인용 전제입니다.", "shaken_by": {"narrative_id": 4, "quote": "원문에 없는 문장입니다만"}}]}}


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "t.db"
        patch.object(database, "DB_PATH", self.path).start()
        self.addCleanup(patch.stopall)
        database.init_db()
        conn = database.get_connection()
        from pipeline.market_today import ensure_schema
        ensure_schema(conn)
        conn.executescript(SEED)
        _mt(conn, 1, 1, "1130", [{"title": "메모리 공급 부족 장기화", "body": "b", "tags": ["메모리"]},
                                 {"title": "AI 버블 논란", "body": "b", "tags": ["AI"]}])
        _mt(conn, 2, 1, "1500", [{"title": "AI 투자 재점화", "body": "b", "tags": ["AI"]}])
        conn.executemany("INSERT INTO market_today_links (mt_id, item_idx, narrative_topic, rule, doc_overlap) VALUES (?,?,?,1,1)",
                         [(1, 0, "메모리"), (1, 1, "AI"), (2, 0, "AI")])
        conn.commit()
        conn.close()
        patch("pipeline.enrich.llm_engine", lambda: "claude-code").start()
        self.calls = []

    def fake(self, out=None):
        def call(prompt):
            self.calls.append(prompt)
            return out if out is not None else good_output(self._m)
        return call

    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def run_(self, trigger="weekly", out=None):
        c = self.conn()
        self._m = wbp.gather(c)
        c.close()
        return wbp.run(trigger, call=self.fake(out))

    def runs(self):
        c = self.conn()
        try:
            return [(r["job"], r["status"]) for r in c.execute("SELECT job, status FROM job_runs WHERE job LIKE 'weekly_big_picture%' ORDER BY id")]
        finally:
            c.close()


class GatherValidateTests(Base):
    def test_gather_window_and_hot_narratives(self):
        c = self.conn()
        m = wbp.gather(c)
        c.close()
        topics = {n["topic"]: n for n in m["narratives"]}
        self.assertEqual(topics["메모리"]["id"], 2)            # 창 안 최신 버전
        self.assertTrue(topics["정치"]["is_new"])               # 첫 버전이 창 안
        self.assertFalse(topics["메모리"]["is_new"])
        self.assertIn("AI", topics)                            # 창 밖 버전이지만 이번 주 Market Today에 걸림
        self.assertFalse(topics["AI"]["in_window"])
        self.assertEqual(m["inputs"], {"narratives": 3, "mt_sessions": 2, "overnight_days": 1})
        self.assertEqual(set(m["mt_items"]), {"mt:1:0", "mt:1:1", "mt:2:0"})
        self.assertEqual(len(m["overnight"]), 2)

    def test_validate_drops_unknown_ids_status_and_quotes(self):
        c = self.conn()
        m = wbp.gather(c)
        c.close()
        v = wbp.validate(good_output(m), m)
        self.assertEqual([s["title"] for s in v["strands"]],
                         ["메모리 부족이 2위권으로 번지고 있습니다", "정치 변수가 새로 들어왔습니다", "AI 수요는 전력이 정합니다"])
        first = v["strands"][0]
        self.assertEqual(first["narratives"], [2])                          # 999 버림
        self.assertEqual(first["evidence"], ["mt:1:0", f"ov:{m['overnight_days'][0]['trade_date']}:0"])   # mt:77 버림
        self.assertEqual(v["strands"][1]["status"], "new")                  # 한국어 상태 → 코드
        self.assertEqual(v["dropped"]["strands"], 2)
        shaken = v["premises"]["contested"]
        self.assertEqual(shaken[0]["shaken_by"], {"narrative_id": 4, "quote": "역대급 이익에도 주가는 따라오지 못했습니다"})
        self.assertIsNone(shaken[1]["shaken_by"])                           # 원문에 없는 인용 → 배지만 뺌
        self.assertEqual(v["dropped"]["quotes"], 1)
        self.assertNotIn("text", json.dumps(v["strands"]))                  # 근거는 id만 — 원문 복사 없음


class RunTests(Base):
    def test_hash_guard_skips_second_run(self):
        r1 = self.run_()
        self.assertEqual(r1["status"], "ok")
        r2 = self.run_()
        self.assertEqual(r2["status"], "skipped")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.runs(), [("weekly_big_picture", "ok"), ("weekly_big_picture", "skipped")])
        c = self.conn()
        row = c.execute("SELECT key, digest FROM source_digests WHERE kind='big_picture'").fetchone()
        c.close()
        self.assertEqual(row["key"], wbp.week_key())
        self.assertEqual(len(json.loads(row["digest"])["strands"]), 3)

    def test_failed_generation_keeps_previous(self):
        self.assertEqual(self.run_()["status"], "ok")
        c = self.conn()
        c.execute("INSERT INTO narratives (topic, version, title, body, kind) VALUES ('반도체', 22, '새 제목입니다', 'b', 'topic')")
        c.commit()
        c.close()
        r = self.run_("manual", out={"strands": [{"title": "x", "status": "mixed", "narratives": [9999]}]})
        self.assertEqual(r["status"], "cooldown")       # 직전 생성 6시간 안 — LLM 없이 거절
        c = self.conn()
        c.execute("UPDATE job_runs SET ran_at = datetime('now', '-7 hours')")
        c.commit()
        c.close()
        r = self.run_("manual", out={"strands": [{"title": "x", "status": "mixed", "narratives": [9999]}]})
        self.assertEqual(r["status"], "failed")
        c = self.conn()
        d = json.loads(c.execute("SELECT digest FROM source_digests WHERE kind='big_picture'").fetchone()[0])
        c.close()
        self.assertEqual(len(d["strands"]), 3)          # 이전 저장분 그대로
        self.assertEqual(self.runs()[-1], ("weekly_big_picture:manual", "error"))

    def test_event_needs_three_new_versions_and_once_per_day(self):
        self.assertEqual(self.run_()["status"], "ok")
        c = self.conn()
        c.execute("UPDATE job_runs SET ran_at = datetime('now', '-2 days')")
        c.execute("UPDATE source_digests SET created_at = datetime('now', '-2 days')")
        c.execute("INSERT INTO narratives (topic, version, title, body, kind) VALUES ('반도체', 22, '반도체 새 버전입니다', 'b', 'topic')")
        c.commit()
        c.close()
        r = self.run_("event")
        self.assertEqual(r["status"], "skipped")        # 지난 생성 뒤 새 버전 1편(정치 v1·메모리 v11은 생성 전)
        c = self.conn()
        c.executemany("INSERT INTO narratives (topic, version, title, body, kind) VALUES (?, ?, ?, 'b', 'topic')",
                      [("HBM", 10, "HBM 새 버전입니다"), ("DRAM", 4, "DRAM 새 버전입니다")])
        c.commit()
        c.close()
        self.assertEqual(self.run_("event")["status"], "ok")
        c = self.conn()
        c.execute("UPDATE source_digests SET created_at = datetime('now', '-1 hours')")   # 같은 초에 넣은 버전과 겹치지 않게
        c.executemany("INSERT INTO narratives (topic, version, title, body, kind) VALUES (?, ?, ?, 'b', 'topic')",
                      [("NAND", 2, "NAND 새 버전입니다"), ("금리", 4, "금리 새 버전입니다"), ("에너지", 13, "에너지 새 버전입니다")])
        c.commit()
        c.close()
        r = self.run_("event")
        self.assertEqual((r["status"], r["reason"]), ("skipped", "오늘 이미 생성 시도함"))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual([j for j, _ in self.runs()][-1], "weekly_big_picture:event")   # 정기 회차 기록과 이름이 다르다

    def test_weekly_budget(self):
        from datetime import datetime, timezone
        now = datetime(2026, 11, 5, 3, 0, tzinfo=timezone.utc)          # 목 12:00 KST
        c = self.conn()
        c.executemany("INSERT INTO job_runs (job, status, summary, ran_at) VALUES (?, ?, 'x', '2026-11-03 00:00:00')",
                      [("weekly_big_picture:manual", "ok")] * (wbp.WEEKLY_BUDGET - 1) + [("weekly_big_picture:event", "error")])
        c.execute("INSERT INTO job_runs (job, status, summary, ran_at) VALUES ('weekly_big_picture', 'skipped', 'x', '2026-11-03 00:00:00')")
        c.commit()
        state = wbp.rebuild_state(c, now)
        c.close()
        self.assertEqual((state["available"], state["reason"], state["budget_left"]), (False, "budget", 0))
        self.assertEqual(state["retry_at"], "2026-11-08 15:00:00")      # 다음 월요일 00:00 KST
        self.assertEqual(wbp.run("manual", call=self.fake(), now=now)["status"], "budget")
        self.assertEqual(self.calls, [])

    def test_cooldown_state(self):
        self.assertEqual(self.run_()["status"], "ok")
        c = self.conn()
        s = wbp.rebuild_state(c)
        c.close()
        self.assertEqual((s["available"], s["reason"]), (False, "cooldown"))
        self.assertIsNotNone(s["retry_at"])
        self.assertEqual(s["budget_left"], wbp.WEEKLY_BUDGET - 1)

    def test_flag_off(self):
        from pipeline.ops import set_flag
        set_flag("weekly_big_picture", False)
        self.assertEqual(self.run_()["status"], "off")
        self.assertEqual(self.calls, [])


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        app.include_router(spine_world.router)
        self.client = TestClient(app)

    def get(self):
        r = self.client.get("/api/spine/world/big-picture")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_fallback_to_mega_before_first_generation(self):
        d = self.get()
        self.assertEqual((d["source"], d["strands"], d["generated_at"]), ("mega", [], None))
        self.assertEqual(d["rebuild"]["available"], True)
        self.assertEqual(d["premises"], {"settled": [], "contested": []})

    def test_generated_strands_with_evidence_and_counts(self):
        self.run_()
        d = self.get()
        self.assertEqual(d["source"], "generated")
        s = d["strands"][0]
        self.assertEqual(s["status"], "strengthening")
        self.assertEqual([c["topic"] for c in s["narratives"]], ["메모리"])
        self.assertEqual([e["text"] for e in s["evidence"]], ["메모리 공급 부족 장기화", "AI 수익성 우려로 반도체지수가 3.4% 하락했다"])
        self.assertTrue(s["evidence"][0]["label"].startswith("Market Today "))
        self.assertEqual((s["mt_topics"], s["mt_sessions"]), (1, 1))
        ai = d["strands"][2]                                       # 메가 군집 밖 서사도 연결 수가 붙는다
        self.assertEqual((ai["mt_topics"], ai["mt_sessions"]), (2, 2))
        self.assertTrue(d["strands"][1]["narratives"][0]["is_new"])
        p = d["premises"]["contested"][0]
        self.assertEqual((p["shaken_by"]["topic"], p["shaken_by"]["version"]), ("주주환원", 8))
        self.assertEqual(d["inputs"], {"narratives": 3, "mt_sessions": 2, "overnight_days": 1})
        self.assertEqual(d["stale_days"], 1)                       # 기준 시각 = 가장 늦은 근거(정치 v1, 1일 전)
        self.assertEqual((d["rebuild"]["available"], d["rebuild"]["reason"]), (False, "cooldown"))

    def test_missing_source_row_drops_evidence_line(self):
        self.run_()
        c = self.conn()
        c.execute("DELETE FROM market_today WHERE id=1")
        c.commit()
        c.close()
        d = self.get()
        self.assertEqual([e["kind"] for e in d["strands"][0]["evidence"]], ["overnight"])

    def test_rebuild_route(self):
        patch("pipeline.enrich._call_claude_code", lambda p, **k: json.dumps(good_output(wbp.gather(self.conn())), ensure_ascii=False)).start()
        r = self.client.post("/api/spine/world/big-picture/rebuild")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "ok")
        r = self.client.post("/api/spine/world/big-picture/rebuild")
        self.assertEqual(r.json()["status"], "cooldown")


class ScheduleTests(unittest.TestCase):
    def test_launchd_weekly_with_catchup(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import install_launchd as il
        jobs = {label: sched for label, _argv, sched in il.JOBS}
        self.assertEqual(jobs["bigpicture"], {"Weekday": 1, "Hour": 7, "Minute": 0})
        self.assertEqual(il.CATCHUP["bigpicture"]["record"], "weekly_big_picture")
        self.assertNotIn("window_h", il.CATCHUP["bigpicture"])

    def test_wrap_session_triggers_event_check(self):
        spec = importlib.util.spec_from_file_location("mt_script", ROOT / "scripts" / "market_today.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        seen = []
        with patch("database.init_db"), patch("pipeline.ops.record_run"), \
                patch("pipeline.weekly_big_picture.run", lambda t: seen.append(t) or {"status": "skipped"}):
            for slot in ("1500", "1600"):   # 장중 회차는 판정하지 않고, 마감 정리 뒤에만
                with patch("pipeline.market_today.run", lambda *a, slot=slot, **k: {"status": "ok", "slot": slot}), \
                        patch.object(sys, "argv", ["market_today.py"]):
                    mod.main()
        self.assertEqual(seen, ["event"])


if __name__ == "__main__":
    unittest.main()
