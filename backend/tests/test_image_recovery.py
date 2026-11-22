"""이미지 해석 복구 (pipeline/image_recovery.py) — 문서 ID 선정·텔레그램 재구성·예산·원자성·미게시 본문 되돌리기."""
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pipeline import image_backfill as ib
from pipeline import image_reading as ir
from pipeline import image_recovery as rec
from pipeline import telegram_deferred

NOTE_INSIGHT = "수출 단가가 급등했다"
SCHEMA = """
CREATE TABLE raw_documents (id INTEGER PRIMARY KEY, source_type TEXT, source_id TEXT, title TEXT, url TEXT,
    published_at TEXT, raw_content TEXT, markdown TEXT, content_hash TEXT, media_json TEXT);
CREATE TABLE enrichments (doc_id INTEGER, content_hash TEXT, model TEXT, UNIQUE(doc_id, content_hash));
CREATE TABLE image_backfill_docs (doc_id INTEGER PRIMARY KEY, done_at TEXT);
CREATE TABLE image_readings (image_key TEXT PRIMARY KEY, status TEXT NOT NULL, kind TEXT, title TEXT,
    insight TEXT, evidence TEXT, events_json TEXT, attempts INTEGER NOT NULL DEFAULT 0, error TEXT,
    model TEXT, updated_at TEXT DEFAULT (datetime('now')));
CREATE TABLE telegram_group_marks (channel TEXT, msg_id INTEGER, joins_prev INTEGER, model TEXT,
    PRIMARY KEY(channel, msg_id));
"""
BAND = rec.BAND


def message(mid, content, minute, images=()):
    return {"message_id": str(mid), "content": content, "date": f"2026-11-20T01:{minute:02d}:00+00:00",
            "link": f"https://t.me/ch/{mid}", "images": list(images)}


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = tempfile.NamedTemporaryFile(suffix=".db")
        conn = self.connect()
        conn.executescript(SCHEMA)
        conn.close()
        self.patches = [patch.object(m, "get_connection", side_effect=self.connect)
                        for m in (rec, ib, ir, telegram_deferred)]
        self.patches += [patch.object(ir, "_load", return_value=(b"x", "png")),
                         patch("pipeline.enrich.llm_engine", return_value="claude-code"),
                         patch("pipeline.llm_config.llm_engine", return_value="claude-code")]
        for p in self.patches:
            p.start()
        self.calls = 0

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.f.close()

    def connect(self):
        c = sqlite3.connect(self.f.name)
        c.row_factory = sqlite3.Row
        return c

    def add(self, ident, source_type, source_id, raw, md=None):
        conn = self.connect()
        conn.execute("INSERT INTO raw_documents (id, source_type, source_id, title, url, published_at, raw_content, "
                     "markdown, content_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                     (ident, source_type, source_id, "", "", "2026-11-20T01:00:00+00:00", raw, md or raw, f"h{ident}"))
        conn.execute("INSERT INTO enrichments VALUES (?,?,?)", (ident, f"h{ident}", "haiku"))
        conn.commit()
        conn.close()

    def mark(self, mid, joins):
        conn = self.connect()
        conn.execute("INSERT INTO telegram_group_marks VALUES ('ch', ?, ?, 'judge')", (mid, int(joins)))
        conn.commit()
        conn.close()

    def fake_call(self, *args, **kwargs):
        self.calls += 1
        return {"kind": "chart", "title": "단가", "insight": NOTE_INSIGHT, "evidence": "", "model": "codex"}

    def row(self, ident):
        conn = self.connect()
        r = conn.execute("SELECT * FROM raw_documents WHERE id=?", (ident,)).fetchone()
        done = conn.execute("SELECT 1 FROM image_backfill_docs WHERE doc_id=?", (ident,)).fetchone() is not None
        conn.close()
        return r, done

    def page(self, *messages):
        seen = {}

        def scrape(channel, before=None):
            seen["args"] = (channel, before)
            return list(messages)
        return scrape, seen

    def test_candidates_are_unprocessed_documents_in_the_mac_mini_band(self):
        self.add(5, "telegram", "ch/5", "old")
        self.add(BAND + 1, "telegram", "ch/10", "new")
        self.add(BAND + 2, "youtube", "v", "video")
        self.add(BAND + 3, "blog", "u", "<p>a</p>")
        conn = self.connect()
        conn.execute("INSERT INTO image_backfill_docs (doc_id) VALUES (?)", (BAND + 3,))
        conn.commit()
        self.assertEqual([r["id"] for r in rec.candidates(conn)], [BAND + 1])
        conn.close()

    def test_telegram_notes_go_after_their_message_and_the_document_is_marked(self):
        self.add(BAND + 1, "telegram", "ch/10", "본문 하나\n\n본문 둘")
        self.mark(10, False)
        self.mark(11, True)
        scrape, seen = self.page(message(9, "앞 글", 0), message(10, "본문 하나", 10, ["https://cdn1.telesco.pe/a"]),
                                 message(11, "본문 둘", 11), message(12, "아직 수집 안 된 다음 글", 12, ["https://cdn1.telesco.pe/z"]))
        with patch.object(ir, "_call", side_effect=self.fake_call):
            out = rec.run(images=2, scrape=scrape)
        r, done = self.row(BAND + 1)
        self.assertEqual(seen["args"], ("ch", 10 + 15 + 1))           # 묶음 전체가 실리는 페이지
        self.assertEqual(self.calls, 1)                               # 같은 페이지의 다른 묶음 이미지는 읽지 않는다
        self.assertEqual(r["raw_content"], "본문 하나\n\n본문 둘")     # 원문은 그대로
        self.assertTrue(r["markdown"].startswith("본문 하나\n\n[이미지 해석·AI"))
        self.assertIn(NOTE_INSIGHT, r["markdown"])
        self.assertTrue(r["markdown"].endswith("본문 둘"))
        self.assertTrue(done)
        conn = self.connect()
        self.assertEqual(conn.execute("SELECT content_hash FROM enrichments").fetchone()[0], r["content_hash"])
        conn.close()
        self.assertEqual(out["changed"], 1)

    def test_telegram_document_whose_text_changed_is_left_alone(self):
        self.add(BAND + 1, "telegram", "ch/10", "예전 본문")
        self.mark(10, False)
        scrape, _ = self.page(message(10, "고쳐진 본문", 10, ["https://cdn1.telesco.pe/a"]))
        with patch.object(ir, "_call", side_effect=self.fake_call):
            out = rec.run(images=2, scrape=scrape)
        r, done = self.row(BAND + 1)
        self.assertEqual((r["markdown"], done, self.calls), ("예전 본문", False, 0))
        self.assertEqual(out["skipped"], {"content differs": 1})

    def test_message_missing_from_the_page_is_skipped_unmarked(self):
        self.add(BAND + 1, "telegram", "ch/10", "본문")
        scrape, _ = self.page(message(30, "다른 글", 10))
        out = rec.run(images=2, scrape=scrape)
        self.assertEqual(out["skipped"], {"message not on page": 1})
        self.assertFalse(self.row(BAND + 1)[1])

    def test_document_needing_more_readings_than_the_budget_stops_the_run(self):
        self.add(BAND + 1, "telegram", "ch/10", "본문")
        self.mark(10, False)
        scrape, _ = self.page(message(10, "본문", 10, ["https://cdn1.telesco.pe/a", "https://cdn1.telesco.pe/b",
                                                      "https://cdn1.telesco.pe/c"]))
        self.add(BAND + 2, "telegram", "ch/20", "둘째")
        self.mark(20, False)
        pages = {"ch": [message(10, "본문", 10, ["https://cdn1.telesco.pe/a", "https://cdn1.telesco.pe/b"]),
                        message(20, "둘째", 40, ["https://cdn1.telesco.pe/c", "https://cdn1.telesco.pe/d"])]}
        with patch.object(ir, "_call", side_effect=self.fake_call):
            out = rec.run(images=3, scrape=lambda channel, before=None: pages[channel])
        self.assertEqual((out["stopped"], self.calls), ("calls", 2))           # 둘째는 남은 예산 1로 못 읽는다
        self.assertEqual((self.row(BAND + 1)[1], self.row(BAND + 2)[1]), (True, False))

    def test_document_larger_than_a_run_does_not_block_the_next(self):
        html = "".join(f'<img class="se-image-resource" data-lazy-src="https://postfiles.pstatic.net/{i}.png"/>' for i in range(3))
        self.add(BAND + 1, "blog", "https://blog.naver.com/x/1", f"<p>많음</p>{html}", md="많음")
        self.add(BAND + 2, "blog", "https://blog.naver.com/x/2",
                 '<p>하나</p><img class="se-image-resource" data-lazy-src="https://postfiles.pstatic.net/one.png"/>', md="하나")
        with patch.object(ir, "_call", side_effect=self.fake_call):
            out = rec.run(images=2)
        self.assertEqual(out["skipped"], {"more readings than a run": 1})
        self.assertEqual((self.calls, self.row(BAND + 1)[1], self.row(BAND + 2)[1]), (1, False, True))

    def test_telegram_without_images_is_marked_without_a_reading(self):
        self.add(BAND + 1, "telegram", "ch/10", "글만")
        self.mark(10, False)
        scrape, _ = self.page(message(10, "글만", 10))
        out = rec.run(images=2, scrape=scrape)
        r, done = self.row(BAND + 1)
        self.assertEqual((out["no_images"], done, r["markdown"]), (1, True, "글만"))

    def test_failed_reading_keeps_the_body_for_the_next_run(self):
        self.add(BAND + 1, "telegram", "ch/10", "본문")
        self.mark(10, False)
        scrape, _ = self.page(message(10, "본문", 10, ["https://cdn1.telesco.pe/a"]))
        with patch.object(ir, "_call", side_effect=RuntimeError("engine")):
            out = rec.run(images=2, scrape=scrape)
        r, done = self.row(BAND + 1)
        self.assertEqual((out["waiting"], done, r["markdown"]), (1, False, "본문"))

    def test_blog_image_read_in_place(self):
        html = '<p>앞 문단</p><img class="se-image-resource" data-lazy-src="https://postfiles.pstatic.net/a.png"/><p>뒤 문단</p>'
        self.add(BAND + 1, "blog", "https://blog.naver.com/x/1", html, md="앞 문단\n\n뒤 문단")
        with patch.object(ir, "_call", side_effect=self.fake_call):
            out = rec.run(images=2)
        r, done = self.row(BAND + 1)
        self.assertEqual((self.calls, done, out["changed"]), (1, True, 1))
        self.assertTrue(r["markdown"].startswith("앞 문단\n\n[이미지 해석·AI"))

    def test_dry_run_reads_and_marks_nothing(self):
        self.add(BAND + 1, "telegram", "ch/10", "본문")
        self.mark(10, False)
        scrape, _ = self.page(message(10, "본문", 10, ["https://cdn1.telesco.pe/a"]))
        with patch.object(ir, "_call", side_effect=self.fake_call):
            out = rec.run(images=2, scrape=scrape, dry_run=True)
        self.assertEqual((self.calls, self.row(BAND + 1)[1]), (0, False))
        self.assertEqual(out["documents"], [{"id": BAND + 1, "result": "would read 1 of 1"}])

    def test_reconcile_restores_the_published_body(self):
        self.add(BAND + 1, "telegram", "ch/10", "본문", md=f"본문\n\n{ir.AI_PREFIX} · 차트] x")
        conn = self.connect()
        conn.execute("INSERT INTO image_backfill_docs (doc_id) VALUES (?)", (BAND + 1,))
        conn.commit()
        conn.close()
        projection = tempfile.NamedTemporaryFile(suffix=".db")
        p = sqlite3.connect(projection.name)
        p.execute("CREATE TABLE raw_documents (id INTEGER PRIMARY KEY, markdown TEXT, content_hash TEXT)")
        p.execute("INSERT INTO raw_documents VALUES (?, '본문', 'published')", (BAND + 1,))
        p.commit()
        p.close()
        out = rec.reconcile(projection.name)
        r, done = self.row(BAND + 1)
        self.assertEqual((out["restored"], r["markdown"], r["content_hash"], done), ([BAND + 1], "본문", "published", False))
        projection.close()


if __name__ == "__main__":
    unittest.main()
