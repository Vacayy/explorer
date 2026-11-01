"""채팅 스터디 도구 — 스터디 이름·번호로 그 프로젝트 자료 전부를 읽는다(chat 70: 전체 검색 결과를 스터디 자료라 부름, 2026-10-23)."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
from pipeline import chat, chat_tools


class StudyToolTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "t.sqlite"
        with patch.object(database, "DB_PATH", self.path):
            database.init_db()
        from pipeline import study_projects
        c = self.connect()
        study_projects.migrate(c)
        c.execute("INSERT INTO blog_sources (url, platform, blog_name, author, is_active) VALUES ('https://blog.naver.com/ranto28','naver','메르의 블로그','메르',1)")
        c.execute("INSERT INTO raw_documents (id, source_type, source_id, title, url, published_at, markdown) VALUES "
                  "(1,'blog','https://blog.naver.com/ranto28/1','배터리 3사','https://blog.naver.com/ranto28/1','2026-07-14T00:00:00','본문 ' * 300)")
        c.execute("INSERT INTO raw_documents (id, source_type, source_id, title, url, published_at, markdown) VALUES "
                  "(2,'blog','https://blog.naver.com/ranto28/2','다른 글','https://blog.naver.com/ranto28/2','2026-10-20T00:00:00','x' * 200)")
        c.execute("INSERT INTO study_projects (id, title) VALUES (8, '(261023) 이차전지, ESS'), (7, '(261021) 시장 업데이트')")
        c.execute("INSERT INTO study_sessions (id, document_id, project_id, title, source_type, published_at, body_kind, body, content_hash) "
                  "VALUES (38, 1, 8, '미국의 중국규제 3종세트로 배터리 3사', 'blog', '2026-07-14', 'original', ?, 'h')", ("배터리 본문 " * 1000,))
        c.execute("INSERT INTO study_project_members (project_id, study_id) VALUES (8, 38)")
        c.execute("INSERT INTO study_annotations (study_id, kind, start_offset, end_offset, exact, comment, revision) VALUES (38,'highlight',0,6,'배터리 본문','이게 핵심?',1)")
        c.commit(); c.close()
        p = patch.object(chat_tools, "get_connection", self.connect)
        p.start(); self.addCleanup(p.stop)

    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def test_by_name_and_number_reads_all_materials(self):
        for q in ("(261023) 이차전지, ESS", "이차전지 ESS", "8", "/study/projects/8"):
            r = chat_tools.get_study(q)
            self.assertEqual(len(r.items), 1, q)
        it = r.items[0]
        self.assertIn("[스터디 자료 · 메르의 블로그]", it["title"])
        self.assertIn("이게 핵심?", it["text"])                         # 내 코멘트
        self.assertIn("앞 5,000자", it["text"])                         # 긴 본문은 잘린다고 밝힘
        self.assertIn("자료 1건 전부", r.note)

    def test_unknown_study_lists_existing(self):
        r = chat_tools.get_study("없는 이름")
        self.assertEqual(r.items, [])
        self.assertIn("(261023) 이차전지, ESS", r.note)

    def test_channel_note_separates_window_from_coverage(self):
        r = chat_tools.list_recent("docs", channel="메르", n=5, days=1)
        self.assertIn("조회 기간 최근 1일", r.note)
        self.assertIn("모두 2건", r.note)
        self.assertIn("가장 이른 글 2026-07-14", r.note)

    def test_prompts_route_study_first_and_guard_label(self):
        self.assertIn("get_study", chat_tools.catalog_text())
        self.assertIn("get_study(project=", chat._router_system())
        synth = chat._synth_system(chat.Turn(question="q", conversation_id=1, ctx={}))
        self.assertIn("[스터디 자료]", synth)
        self.assertIn("조회 기간을 수집 시작으로 말하지 않는다", synth)


if __name__ == "__main__":
    unittest.main()
