"""인물 1단계 (ia-redesign §4.23 A안) — 이름 자동 정리(소프트 병합)·역할 자동 분류·전제 '누가' 대응 표·메모 저자·id 기반 API.

- 묶는 규칙은 결정적이고, 애매하면 그대로 둔다(한 낱말 이름 KEEP_APART·후보 여럿·집안 이름·회사가 주인인 이름).
- 소프트 병합: 진 쪽 엔티티·문서 연결을 지우지 않는다. 되돌리면 status가 돌아오고 다시 묶지 않는다.
- 집계·상세는 묶인 이름을 대표 인물 한 사람으로(같은 문서는 한 번) 센다.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import database
from pipeline import people, person_reads


def _docs(conn, start, n, *, source_type="telegram", prefix="d", days_ago=1):
    ids = []
    for i in range(n):
        did = start + i
        conn.execute("INSERT INTO raw_documents (id, source_type, source_id, title, published_at, fetched_at) "
                     "VALUES (?, ?, ?, ?, datetime('now', ?), datetime('now', ?))",
                     (did, source_type, f"{prefix}{did}", f"doc {did}", f"-{days_ago} days", f"-{days_ago} days"))
        ids.append(did)
    return ids


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch.object(database, "DB_PATH", Path(self.tmp.name) / "t.db").start()
        self.addCleanup(patch.stopall)
        database.init_db()
        self.conn = database.get_connection()
        self.addCleanup(self.conn.close)
        c = self.conn
        ents = [
            (1, "person", "하워드 막스"), (2, "person", "호워드 막스"), (3, "person", "Howard Marks"),
            (4, "person", "젠슨 황"), (5, "person", "젠슨황"), (6, "company", "젠슨 황"),
            (7, "person", "{'name': '젠슨 황', 'as_written': 'x'}"),
            (8, "person", "스탠리 드러켄밀러"), (9, "person", "드러켄밀러"),
            (10, "person", "케빈 워시"), (11, "person", "워시"),
            (12, "person", "트럼프"), (13, "person", "도널드 트럼프"), (14, "person", "멜라니아 트럼프"), (15, "person", "에릭 트럼프"),
            (16, "person", "월트 디즈니"), (17, "company", "월트 디즈니"),
            (18, "person", "플라비우 보우소나루"), (19, "person", "보우소나루"),
            (20, "person", "이재명"), (21, "person", "이재명 대통령"),
            (30, "company", "NVIDIA"), (31, "topic", "매크로"), (32, "topic", "금리"), (33, "topic", "채권"), (34, "topic", "재정"),
            (40, "person", "Amy Hood"), (41, "person", "James Anderson"),
        ]
        c.executemany("INSERT INTO entities (id, type, name) VALUES (?, ?, ?)", ents)
        link = lambda doc, eid, lt="person": c.execute(
            "INSERT OR IGNORE INTO entity_links (doc_id, entity_id, link_type) VALUES (?, ?, ?)", (doc, eid, lt))
        # 막스 20건 · 호워드 1 · 영문 1(같은 문서 하나는 막스와 겹친다)
        marks = _docs(c, 100, 20)
        for d in marks:
            link(d, 1)
        _docs(c, 130, 1)
        link(100, 2)
        link(101, 3)
        link(130, 3)
        # 젠슨 황 30 · 붙여 쓴 이름 1 · 회사로 잘못 분류 1 · 잔여물 1
        jensen = _docs(c, 200, 30)
        for d in jensen:
            link(d, 4)
            link(d, 30, "stock")
        _docs(c, 240, 3)
        link(240, 5)
        link(241, 6, "stock")
        link(242, 7)
        # 드러켄밀러 — 약칭 8건 · 전체 이름 6건, 함께 언급(매크로·금리·채권·재정) 겹침
        _docs(c, 300, 14)
        for d in range(300, 308):
            link(d, 9)
        for d in range(308, 314):
            link(d, 8)
        for d in range(300, 314):
            for t in (31, 32, 33, 34):
                link(d, t, "topic")
        # 워시 — 한 낱말 이름은 묻지 않고 따로 둔다
        _docs(c, 400, 6)
        for d in range(400, 405):
            link(d, 10)
        link(405, 11)
        # 트럼프 — 도널드 트럼프는 별칭 사전, 집안 이름은 후보 여럿이라 그대로
        _docs(c, 500, 12)
        for d in range(500, 510):
            link(d, 12)
        link(510, 13)
        link(511, 14)
        link(511, 15)
        # 월트 디즈니 — 회사가 주인 이름(회사 3건 > 인물 1건×3배 미만) → 분류 교정 안 함
        _docs(c, 600, 4)
        link(600, 16)
        for d in (601, 602, 603):
            link(d, 17, "stock")
        # 보우소나루 — 전체 이름 쪽이 덜 쓰여(1 < 5) 그대로
        _docs(c, 700, 4)
        link(700, 18)
        for d in (701, 702, 703):
            link(d, 19)
        # 직함 꼬리
        _docs(c, 800, 3)
        link(800, 20)
        link(801, 20)
        link(802, 21)
        # 오크트리 메모(저자 연결) — 하나는 이미 '언급'으로 걸려 있다
        memos = _docs(c, 900, 3, source_type="memo", prefix="oaktree/m")
        link(memos[0], 1)
        c.execute("INSERT INTO follows (entity_id) VALUES (4)")
        c.commit()


class PlanTests(Base):
    def test_rules_and_survivors(self):
        p = people.plan(self.conn)
        groups = {g["survivor_name"]: {m["name"]: m["rule"] for m in g["members"]} for g in p["groups"]}
        self.assertEqual(groups["하워드 막스"], {"호워드 막스": "spelling", "Howard Marks": "english"})
        self.assertEqual(groups["젠슨 황"], {"젠슨황": "spacing", "젠슨 황": "type_fix", "{'name': '젠슨 황', 'as_written': 'x'}": "cleanup"})
        self.assertEqual(groups["스탠리 드러켄밀러"], {"드러켄밀러": "abbrev"})          # 대표는 전체 이름(약칭이 더 많아도)
        self.assertEqual(groups["트럼프"], {"도널드 트럼프": "alias"})
        self.assertEqual(groups["이재명"], {"이재명 대통령": "cleanup"})
        self.assertNotIn("월트 디즈니", groups)                                    # 회사가 주인 이름
        self.assertNotIn("플라비우 보우소나루", groups)
        self.assertNotIn("보우소나루", groups)
        held = {h["name"]: h["reason"] for h in p["held"]}
        self.assertEqual(held["워시"], "keep_apart")
        self.assertEqual(held["트럼프"], "several")                                 # 멜라니아·에릭 트럼프
        self.assertEqual(held["보우소나루"], "low_overlap")

    def test_apply_is_soft_idempotent_and_logged(self):
        n_ent = self.conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        p = people.plan(self.conn)
        stats = people.apply(self.conn, p)
        self.assertEqual(stats["merged"], p["stats"]["names"])
        c = self.conn
        self.assertEqual(c.execute("SELECT status FROM entities WHERE id=2").fetchone()[0], "merged")
        self.assertEqual(c.execute("SELECT COUNT(*) FROM entities").fetchone()[0], n_ent)    # 아무것도 지우지 않는다
        self.assertEqual(c.execute("SELECT COUNT(*) FROM entity_links WHERE entity_id=6").fetchone()[0], 1)   # 연결도 그대로
        m = c.execute("SELECT type, survivor_id, rule, prev_status FROM entity_merges WHERE old_entity_id=6").fetchone()
        self.assertEqual(tuple(m), ("person_company", 4, "type_fix", "active"))
        self.assertEqual(people.apply(c, people.plan(c)), {"kept": p["stats"]["names"]})
        log = dict(c.execute("SELECT verdict, COUNT(*) FROM curation_log WHERE kind='person' GROUP BY verdict").fetchall())
        self.assertEqual(log["approve"], p["stats"]["names"])
        self.assertEqual(log["hold"], p["stats"]["held"])

    def test_split_restores_and_is_not_merged_again(self):
        people.apply(self.conn, people.plan(self.conn))
        self.assertTrue(people.split(self.conn, 3))
        c = self.conn
        self.assertEqual(c.execute("SELECT status FROM entities WHERE id=3").fetchone()[0], "active")
        self.assertEqual(c.execute("SELECT verdict FROM curation_log WHERE kind='person' AND target_id=3").fetchone()[0], "reject")
        p = people.plan(c)
        names = {m["name"] for g in p["groups"] for m in g["members"]}
        self.assertNotIn("Howard Marks", names)
        self.assertEqual(people.resolve_id(c, 3), 3)
        self.assertFalse(people.split(c, 3))


class ReadTests(Base):
    def setUp(self):
        super().setUp()
        people.curate(self.conn)

    def test_resolve(self):
        c = self.conn
        self.assertEqual(people.resolve_name(c, "호워드 막스"), 1)
        self.assertEqual(people.resolve_name(c, "젠슨황"), 4)
        self.assertEqual(people.resolve_id(c, 6), 4)                         # 회사로 잘못 분류됐던 이름도 대표로
        self.assertIsNone(people.resolve_name(c, "없는 사람"))
        self.assertIsNone(people.resolve_id(c, 30))                          # 회사는 인물이 아니다

    def test_aggregate_counts_merged_names_once(self):
        from routers.spine_person import aggregate_people
        rows = {r["name"]: r for r in aggregate_people(self.conn)}
        self.assertEqual(rows["하워드 막스"]["doc_count"], 22)              # 20 + 영문 1(겹치는 1건은 한 번) + 메모 언급 1
        self.assertEqual(rows["젠슨 황"]["doc_count"], 33)                  # 30 + 붙여 쓴 1 + 회사 1 + 잔여물 1
        self.assertTrue(rows["젠슨 황"]["following"])
        self.assertNotIn("호워드 막스", rows)
        self.assertNotIn("젠슨황", rows)
        self.assertNotIn("젠슨 황", [s for s in rows["젠슨 황"]["top_stocks"]])   # 묶인 회사 이름은 함께 언급 종목이 아니다

    def test_authors_roles_and_who(self):
        c = self.conn
        self.assertEqual(c.execute("SELECT COUNT(*) FROM entity_links WHERE entity_id=1 AND link_type='author'").fetchone()[0], 3)
        roles = people.roles(c)
        self.assertEqual((roles[1]["role"], roles[1]["org"], roles[1]["source"]), ("guru", "오크트리 캐피털", "memo"))
        self.assertEqual(roles[8]["role"], "guru")                           # 전제 원장 '누가'(Druckenmiller)
        self.assertEqual((roles[12]["role"], roles[12]["org"]), ("policy", "미국 대통령"))
        self.assertEqual((roles[4]["role"], roles[4]["org_code"]), ("executive", "NVDA"))
        self.assertEqual(roles[10]["role"], "policy")                        # 케빈 워시 — 연준
        self.assertNotIn(11, roles)                                          # 한 낱말 '워시'는 따로 두고 역할도 없다
        who = people.who_people(c, "Marks · BIS · Summers · Grantham(거품 쪽)")
        self.assertEqual([(w["kind"], w["entity_id"]) for w in who], [("person", 1), ("org", None), ("person", None), ("person", None)])
        self.assertEqual(who[0]["name"], "하워드 막스")
        self.assertEqual(who[3]["label"], "Grantham(거품 쪽)")

    def test_transcript_executive_needs_link_to_that_call(self):
        c = self.conn
        c.execute("INSERT INTO transcript_follow (ticker, company_name) VALUES ('MSFT', 'Microsoft'), ('COHR', 'Coherent')")
        _docs(c, 1000, 2, source_type="transcript")
        c.execute("UPDATE raw_documents SET markdown='**Amy Hood** (Executive Vice President and Chief Financial Officer): hi' WHERE id=1000")
        c.execute("UPDATE raw_documents SET markdown='**James Anderson** (Chief Executive Officer): hi' WHERE id=1001")
        c.execute("INSERT INTO transcripts (raw_doc_id, ticker, fiscal_year, fiscal_period, provider) VALUES (1000, 'MSFT', 2026, 'Q1', 'alphavantage'), (1001, 'COHR', 2026, 'Q1', 'alphavantage')")
        c.execute("INSERT INTO entity_links (doc_id, entity_id, link_type) VALUES (1000, 40, 'person')")   # Amy Hood는 그 컨콜에 걸림
        c.commit()
        rows = {r["entity_id"]: r for r in people.classify_roles(c)}
        self.assertEqual((rows[40]["role"], rows[40]["org"], rows[40]["title"]), ("executive", "Microsoft", "CFO"))
        self.assertNotIn(41, rows)                                           # 컨콜에 안 걸린 동명이인 가능성 — 붙이지 않는다

    def test_home_and_detail(self):
        c = self.conn
        h = person_reads.home(c)
        self.assertEqual(h["summary"]["followed"], 1)
        self.assertEqual([r["name"] for r in h["followed"]], ["젠슨 황"])
        self.assertEqual(h["followed"][0]["role"]["role"], "executive")
        rec = {r["name"]: r for r in h["recorded"]}
        self.assertEqual(len(rec["하워드 막스"]["premises"]), 4)
        self.assertEqual(rec["래리 서머스"]["entity_id"], None)               # 인물 엔티티가 없으면 만들지 않는다
        self.assertEqual(h["recorded_status"], "ok")
        d = person_reads.detail(c, 2)                                         # 묶인 이름의 id → 대표
        self.assertEqual((d["entity_id"], d["requested_id"], d["name"]), (1, 2, "하워드 막스"))
        self.assertEqual([m["name"] for m in d["merged_names"]], ["Howard Marks", "호워드 막스"])   # 문서 많은 순
        self.assertEqual((d["own_total"], d["own_source"]), (3, "오크트리 캐피털"))
        self.assertEqual(d["mentions"]["count"], 22)                          # 언급 21 + 메모 하나가 '언급'으로도 걸림
        self.assertEqual(d["cited_total"], 21)                                # 본인 글은 인용에서 뺀다
        self.assertEqual(len(d["premises"]), 4)
        low = next(p for p in d["premises"] if p["key"] == "low_rate_over")
        self.assertEqual([w["label"] for w in low["co_holders"]], ["BIS", "Summers", "El-Erian"])   # 자기 자신은 뺀다
        self.assertIsNone(person_reads.detail(c, 30))
        jensen = person_reads.detail(c, 4)
        self.assertEqual([m["name"] for m in jensen["merged_names"]], ["젠슨황"])   # 잔여물·같은 이름 회사는 한 줄로 안 보인다

    def test_premise_failure_is_block_level(self):
        with patch("pipeline.era.layer_premises", side_effect=RuntimeError("x")):
            h = person_reads.home(self.conn)
            d = person_reads.detail(self.conn, 1)
        self.assertEqual((h["recorded_status"], h["recorded"]), ("error", []))
        self.assertEqual(len(h["followed"]), 1)
        self.assertEqual((d["premises_status"], d["premises"]), ("error", []))
        self.assertEqual(d["own_total"], 3)


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        people.curate(self.conn)
        from main import app
        self.client = TestClient(app)

    def test_routes(self):
        r = self.client.get("/api/spine/person/home")
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.get("/api/spine/person/13")                           # 도널드 트럼프 → 트럼프
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["entity_id"], r.json()["requested_id"]), (12, 13))
        self.assertEqual(self.client.get("/api/spine/person/30").status_code, 404)
        self.assertEqual(self.client.get("/api/spine/person/resolve", params={"name": "Howard Marks"}).json(),
                         {"entity_id": 1, "name": "하워드 막스"})
        self.assertEqual(self.client.get("/api/spine/person/resolve", params={"name": "없는 사람"}).json(),
                         {"entity_id": None, "name": None})
        self.assertEqual(self.client.get("/api/spine/person/followed").status_code, 200)   # 이름 경로와 겹치지 않는다
        st = self.client.get("/api/spine/regimes/state").json()
        low = next(p for p in st["premises"] if p["key"] == "low_rate_over")
        self.assertEqual(low["who_people"][0], {"label": "Marks", "kind": "person", "entity_id": 1, "name": "하워드 막스"})


if __name__ == "__main__":
    unittest.main()
