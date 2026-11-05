"""Market Today 화두 → 내러티브 연결·후보·앞당김 (ia-redesign §9). LLM 없음."""
import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from pipeline import market_today as mt
from pipeline import market_today_links as L
from pipeline import narrative as nar

BASE = """
CREATE TABLE entities(id INTEGER PRIMARY KEY, type TEXT, name TEXT, status TEXT DEFAULT 'active');
CREATE TABLE entity_links(id INTEGER PRIMARY KEY, doc_id INTEGER, entity_id INTEGER, link_type TEXT);
CREATE TABLE narratives(id INTEGER PRIMARY KEY, topic TEXT, version INTEGER, title TEXT, body TEXT, kind TEXT DEFAULT 'topic',
                        created_at TEXT DEFAULT (datetime('now')), superseded_at TEXT);
"""


def topic(title, tags, refs):
    return {"title": title, "body": "", "tags": tags, "continuing": False, "refs": refs, "echo": len(refs)}


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "t.sqlite"
        conn = self.connect()
        conn.executescript(BASE + mt.SCHEMA)
        L.ensure_schema(conn)
        # 주제 엔티티 — '지정학'은 sector·theme 두 개(§8.8 중복)
        ents = [(1, "theme", "AI"), (2, "sector", "반도체"), (3, "sector", "지정학"), (4, "theme", "지정학"),
                (5, "theme", "메모리"), (6, "theme", "정치"), (7, "company", "AI")]
        conn.executemany("INSERT INTO entities (id, type, name) VALUES (?,?,?)", ents)
        conn.executemany("INSERT INTO narratives (topic, version, created_at, superseded_at) VALUES (?,?,?,?)", [
            ("AI", 3, "2026-10-28 06:00:00", None), ("AI", 2, "2026-10-20 06:00:00", "2026-10-28 06:00:00"),
            ("반도체", 1, "2026-10-31 08:00:00", None), ("지정학", 5, "2026-11-03 10:00:00", None),
            ("메모리", 2, "2026-11-03 11:00:00", None)])
        conn.commit()
        conn.close()
        p = patch.object(mt, "get_connection", self.connect)
        p.start()
        self.addCleanup(p.stop)

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        return conn

    def link(self, conn, doc, *entity_ids, link_type="topic"):
        conn.executemany("INSERT INTO entity_links (doc_id, entity_id, link_type) VALUES (?,?,?)",
                         [(doc, e, link_type) for e in entity_ids])

    def session(self, conn, day, slot, items, docs):
        sources = {f"S{i}": {"kind": "telegram", "publisher": f"p{i}", "title": "t", "url": None, "doc_id": d,
                             "published_at": None, "echo": 1} for i, d in enumerate(docs, 1)}
        cur = conn.execute("INSERT INTO market_today (trade_date, slot, window_start, window_end, items_json, sources_json, doc_count) "
                           "VALUES (?,?,?,?,?,?,?)", (day, slot, "", "", json.dumps(items, ensure_ascii=False),
                                                     json.dumps(sources), len(docs)))
        return cur.lastrowid

    # ---------- 짝 찾기 규칙 ----------

    def test_rule1_tag_equal_needs_one_linked_source(self):
        self.assertEqual(L.match_item(["메모리", "반도체"], [{"메모리"}], ["메모리", "반도체"]),
                         [{"topic": "메모리", "rule": 1, "doc_overlap": 1}])
        self.assertEqual(L.match_item(["메모리"], [set()], ["메모리"]), [])           # 태그만 같고 출처가 안 걸리면 아님
        self.assertEqual(L.match_item([" ai "], [{"AI"}], ["AI"])[0]["rule"], 1)     # 공백·대소문자 무시

    def test_rule2_partial_tag_and_rule3_overlap_need_two_sources(self):
        both = [{"AI", "반도체"}, {"AI", "반도체"}]
        self.assertEqual(L.match_item(["AI 투자", "설비투자"], both, ["AI", "반도체"]),
                         [{"topic": "AI", "rule": 2, "doc_overlap": 2}, {"topic": "반도체", "rule": 3, "doc_overlap": 2}])
        self.assertEqual(L.match_item(["AI 투자"], [{"AI"}], ["AI"]), [])          # 부분 일치여도 출처 1건이면 아님

    def test_order_is_rule_then_overlap(self):
        docs = [{"반도체", "지정학"}, {"반도체", "지정학"}, {"지정학"}]
        got = L.match_item(["메모리"], docs + [{"메모리"}], ["반도체", "지정학", "메모리"])
        self.assertEqual([g["topic"] for g in got], ["메모리", "지정학", "반도체"])

    def test_same_name_entities_count_a_document_once(self):
        conn = self.connect()
        self.link(conn, 10, 3, 4)       # 지정학 sector·theme 둘 다 같은 문서에
        self.link(conn, 11, 3)
        self.link(conn, 12, 7, link_type="mention")   # 회사 'AI' 언급은 주제 연결이 아니다
        mid = self.session(conn, "2026-11-03", "1000", [topic("이란 공습", ["이란"], ["S1", "S2"]), topic("x", ["AI"], ["S3"])],
                           [10, 11, 12])
        L.link_narratives(conn, mid)
        rows = conn.execute("SELECT item_idx, narrative_topic, rule, doc_overlap FROM market_today_links").fetchall()
        self.assertEqual([tuple(r) for r in rows], [(0, "지정학", 3, 2)])

    def test_read_attaches_live_narratives_and_partial_when_not_linked(self):
        conn = self.connect()
        self.link(conn, 20, 1)
        self.link(conn, 21, 1, 2)
        mid = self.session(conn, "2026-11-03", "1000", [topic("AI 버블", ["AI 투자"], ["S1", "S2"]), topic("호주 금리", ["호주"], [])],
                           [20, 21])
        conn.commit()
        r = mt.read("2026-11-03")
        self.assertFalse(r["current"]["links_ready"])                 # 계산 전 — 칩 줄 없음
        self.assertEqual([t["narratives"] for t in r["current"]["topics"]], [[], []])
        L.link_narratives(conn, mid)
        conn.commit()
        r = mt.read("2026-11-03")
        self.assertTrue(r["current"]["links_ready"])
        chips = r["current"]["topics"][0]["narratives"]
        self.assertEqual([(c["topic"], c["version"], c["rule"]) for c in chips], [("AI", 3, 2)])   # 살아 있는 v3
        self.assertEqual(r["current"]["topics"][1]["narratives"], [])

    # ---------- 후보 ----------

    def seed_candidates(self, conn):
        s1 = self.session(conn, "2026-11-03", "1540", [topic("중간선거 경계", ["중간선거", "미국 정치"], ["S1"])], [30])
        s2 = self.session(conn, "2026-11-04", "1000", [topic("개표와 선물", ["중간선거", "선물"], ["S1"]),
                                                       topic("이란 공습", ["이란", "금"], ["S2"])], [31, 40])
        s3 = self.session(conn, "2026-11-04", "1300", [topic("민주당 우세", ["중간선거", "개표"], ["S1"]),
                                                       topic("케슘섬 공습", ["이란", "케슘섬"], ["S2"]),
                                                       topic("실적 시즌", ["실적"], [])], [32, 41])
        s4 = self.session(conn, "2026-11-04", "1500", [topic("케슘섬 제한 공습", ["케슘섬"], ["S1"]),
                                                       topic("실적 호조", ["실적", "AI"], [])], [42])
        wrap = self.session(conn, "2026-11-04", "1600", [topic("하루 정리 실적", ["실적"], []),
                                                         topic("오늘의 반도체", ["반도체 규제"], [])], [])
        return s1, s2, s3, s4, wrap

    def test_candidate_needs_two_days_three_sessions_and_watching_is_one_day(self):
        conn = self.connect()
        self.seed_candidates(conn)
        r = L.refresh_candidates(conn, today=date(2026, 11, 5))
        self.assertEqual((r["pending"], r["watching"]), (1, 1))
        rows = {x["tag"]: x for x in L.list_candidates(conn)}
        self.assertEqual(rows["중간선거"]["status"], "pending")
        self.assertEqual((rows["중간선거"]["days"], rows["중간선거"]["sessions"]), (2, 3))
        self.assertEqual(rows["이란"]["status"], "watching")           # 하루 3회차 — 버튼 없이 표시
        self.assertEqual(rows["이란"]["name"], "이란 · 케슘섬")
        self.assertNotIn("실적", rows)                                   # 일반어 — 3회차(마감 정리 빼면 2)라도 후보 아님
        self.assertNotIn("반도체규제", rows)                              # 마감 정리 화두는 세지 않는다

    def test_tag_with_live_narrative_and_two_sessions_are_not_candidates(self):
        conn = self.connect()
        for slot, day in (("1000", "2026-11-03"), ("1000", "2026-11-04"), ("1300", "2026-11-04")):
            self.session(conn, day, slot, [topic("AI", ["ai"], [])], [])
        self.session(conn, "2026-11-03", "1300", [topic("호주", ["호주"], [])], [])
        self.session(conn, "2026-11-04", "1500", [topic("호주", ["호주"], [])], [])
        L.refresh_candidates(conn, today=date(2026, 11, 5))
        self.assertEqual(L.list_candidates(conn), [])

    def test_merge_suggested_when_sources_overlap_a_new_narrative(self):
        conn = self.connect()
        self.seed_candidates(conn)
        self.link(conn, 30, 6)
        conn.execute("INSERT INTO narratives (topic, version, created_at) VALUES ('정치', 1, '2026-11-04 06:14:00')")
        L.refresh_candidates(conn, today=date(2026, 11, 5))
        self.assertIsNone(L.list_candidates(conn)[0]["merge_into"])     # 1건 겹침으로는 제안하지 않는다
        self.link(conn, 31, 6)
        L.refresh_candidates(conn, today=date(2026, 11, 5))
        merge = L.list_candidates(conn)[0]["merge_into"]
        self.assertEqual((merge["topic"], merge["overlap"]), ("정치", 2))
        # 오래된 서사(첫 버전이 후보보다 훨씬 전)는 더 많이 겹쳐도 합치기 대상이 아니다
        conn.execute("INSERT INTO narratives (topic, version, created_at, superseded_at) VALUES ('지정학', 1, '2026-08-01', '2026-08-10')")
        self.link(conn, 30, 3)
        self.link(conn, 31, 3)
        self.link(conn, 32, 3)
        L.refresh_candidates(conn, today=date(2026, 11, 5))
        self.assertEqual(L.list_candidates(conn)[0]["merge_into"]["topic"], "정치")

    def test_approve_merge_links_tag_to_narrative(self):
        conn = self.connect()
        s1, s2, s3, *_ = self.seed_candidates(conn)
        self.link(conn, 30, 6)
        self.link(conn, 31, 6)
        conn.execute("INSERT INTO narratives (topic, version, created_at) VALUES ('정치', 1, '2026-11-04 06:14:00')")
        L.refresh_candidates(conn, today=date(2026, 11, 5))
        out = L.approve(conn, "중간선거")
        self.assertEqual((out["mode"], out["narrative_topic"]), ("merge", "정치"))
        got = {r["mt_id"] for r in conn.execute("SELECT mt_id FROM market_today_links WHERE narrative_topic='정치'")}
        self.assertEqual(got, {s1, s2, s3})                              # 출처가 안 걸린 회차도 태그 일치로
        self.assertEqual(L.list_candidates(conn)[:1][0]["tag"], "이란")  # 합친 후보는 카드에서 내려간다
        self.assertIsNone(L.approve(conn, "중간선거"))                    # 두 번은 안 된다

    def test_approve_new_registers_topic_without_generating(self):
        conn = self.connect()
        self.seed_candidates(conn)
        L.refresh_candidates(conn, today=date(2026, 11, 5))
        out = L.approve(conn, "중간선거")
        self.assertEqual((out["mode"], out["narrative_topic"]), ("new", "중간선거"))
        self.assertEqual(L.pending_new_topics(conn), ["중간선거"])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM narratives WHERE topic='중간선거'").fetchone()[0], 0)
        L.refresh_candidates(conn, today=date(2026, 11, 5))              # 다시 계산해도 승인 상태 유지
        self.assertEqual(next(x for x in L.list_candidates(conn) if x["tag"] == "중간선거")["status"], "approved")
        self.assertIsNone(L.approve(conn, "이란"))                        # 관찰 중은 승인 대상이 아니다

    def test_dismiss_hides_for_fourteen_days(self):
        conn = self.connect()
        self.seed_candidates(conn)
        L.refresh_candidates(conn, today=date(2026, 11, 5))
        out = L.dismiss(conn, "중간선거", today=date(2026, 11, 5))
        self.assertEqual(out["dismissed_until"], "2026-11-19")
        L.refresh_candidates(conn, today=date(2026, 11, 6))
        self.assertNotIn("중간선거", [x["tag"] for x in L.list_candidates(conn)])
        # 같은 태그 회차가 더 나와도 기간 안이면 다시 올리지 않는다
        self.session(conn, "2026-11-06", "0930", [topic("중간선거 결과", ["중간선거"], [])], [])
        L.refresh_candidates(conn, today=date(2026, 11, 6))
        self.assertNotIn("중간선거", [x["tag"] for x in L.list_candidates(conn)])
        # 기간이 끝나면 조건대로 다시 판정(창 안 회차가 남아 있으면 후보)
        for i, slot in enumerate(("0930", "1130", "1500")):
            self.session(conn, "2026-11-20", slot, [topic("중간선거 여파", ["중간선거"], [])], [])
        self.session(conn, "2026-11-19", "1130", [topic("중간선거 여파", ["중간선거"], [])], [])
        L.refresh_candidates(conn, today=date(2026, 11, 20))
        self.assertEqual(next(x for x in L.list_candidates(conn) if x["tag"] == "중간선거")["status"], "pending")

    # ---------- 빈도·앞당김 ----------

    def test_boost_needs_three_sessions_this_week_and_stale_narrative(self):
        conn = self.connect()
        conn.execute("UPDATE narratives SET created_at=datetime('now','-5 days') WHERE topic='AI' AND superseded_at IS NULL")
        conn.execute("UPDATE narratives SET created_at=datetime('now','-1 days') WHERE topic='메모리'")
        self.link(conn, 50, 1, 5)
        for day, slot in (("2026-11-03", "1000"), ("2026-11-03", "1300"), ("2026-11-04", "1000"), ("2026-11-04", "1600")):
            mid = self.session(conn, day, slot, [topic("x", ["AI", "메모리"], ["S1"])], [50])
            L.link_narratives(conn, mid)
        f = L.frequency(conn, "2026-11-02")
        self.assertEqual((f["AI"]["topics"], f["AI"]["sessions"]), (3, 3))     # 16:00 마감 정리는 세지 않는다
        self.assertEqual(L.boosted_topics(conn, "2026-11-02"), {"AI"})        # 메모리는 갱신 하루 — 앞당기지 않는다
        self.assertEqual(L.boosted_topics(conn, "2026-11-04"), set())         # 지난주 회차는 이번 주로 안 센다
        self.assertEqual(L.strand_counts(conn, ["AI", "메모리"], f, {"AI"}), {"mt_topics": 3, "mt_sessions": 3, "boost": True})

    def test_refresh_order_moves_boosted_first_without_adding(self):
        self.assertEqual(nar._order_by_boost(["반도체", "메모리", "AI"], {"AI", "에너지"}), ["AI", "반도체", "메모리"])
        rows = [{"name": "a"}, {"name": "b"}]
        self.assertEqual(nar._order_by_boost(rows, {"b"}, key=lambda r: r["name"]), [{"name": "b"}, {"name": "a"}])

    # ---------- 타임라인 ----------

    def test_timeline_cells(self):
        conn = self.connect()
        self.link(conn, 60, 5)
        a = self.session(conn, "2026-11-04", "1000", [topic("메모리 비용", ["메모리"], ["S1"])], [60])
        b = self.session(conn, "2026-11-04", "1300", [topic("다른 얘기", ["호주"], [])], [])
        self.session(conn, "2026-11-04", "1540", [topic("아직", ["메모리"], ["S1"])], [60])   # 연결 계산 전
        for m in (a, b):
            L.link_narratives(conn, m)
        nid = conn.execute("SELECT id FROM narratives WHERE topic='메모리'").fetchone()[0]
        now = datetime(2026, 11, 5, 2, 0, tzinfo=timezone.utc)        # 11/5 11:00 KST — 오늘 회차 일부 남음
        t = L.timeline(conn, nid, now=now)
        self.assertEqual([d["trade_date"] for d in t["days"]], ["2026-11-05", "2026-11-04"])
        self.assertEqual([c["state"] for c in t["days"][0]["cells"]], ["absent", "scheduled", "scheduled", "scheduled"])
        self.assertEqual([c["slot"] for c in t["days"][1]["cells"]], ["1000", "1300", "1540"])   # 옛 회차 날은 옛 칸
        self.assertEqual([c["state"] for c in t["days"][1]["cells"]], ["linked", "unlinked", "scheduled"])
        self.assertEqual([i["title"] for i in t["items"]], ["메모리 비용"])
        self.assertEqual((t["collected_since"], t["week_sessions"]), ("2026-11-04", 1))
        late = L.timeline(conn, nid, now=datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc))   # 19:00 — 오늘 회차 없음이면 오늘 줄 없음
        self.assertEqual([d["trade_date"] for d in late["days"]], ["2026-11-04"])
        self.assertIsNone(L.timeline(conn, 9999))


if __name__ == "__main__":
    unittest.main()
