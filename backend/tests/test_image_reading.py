"""이미지 해석 (docs/specs/image-reading.md) — 줄바꿈 정규화·자리 치환·문서 단위 원자성·텔레그램 삽입·AI 줄 제외."""
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pipeline import image_reading as ir
from pipeline.base import RawDoc
from pipeline.normalize import _html_to_text, to_markdown

NOTE = "[이미지 해석·AI · 차트] 수출 단가 — 급등했다."


class LineBreakTests(unittest.TestCase):
    def test_inline_elements_do_not_split_sentences(self):
        html = '<div class="se-main-container"><p>이로 인해 <b>일자리의 27%가 영향</b>되며 흔들린다.</p>' \
               '<div><div><p>​</p></div></div><p>둘째&nbsp;문단</p></div>'
        self.assertEqual(_html_to_text(html), "이로 인해 일자리의 27%가 영향되며 흔들린다.\n\n둘째 문단")

    def test_blank_runs_collapse_to_one_and_br_breaks(self):
        html = "<div><div><div><p>a</p></div></div></div><div></div><div></div><p>b<br>c</p>"
        self.assertEqual(_html_to_text(html), "a\n\nb\nc")

    def test_table_cells_keep_separated(self):
        self.assertEqual(_html_to_text("<table><tr><td>매출</td><td>1,230</td></tr></table>"), "매출 1,230")


class BlogImageTests(unittest.TestCase):
    def doc(self, html):
        return RawDoc(source_type="blog", source_id="u", title="DRAM 가격", url="https://blog.naver.com/x/1",
                      published_at="2026-10-23T00:00:00+00:00", raw_content=html, kind="html")

    def test_image_replaced_in_place_with_context_around_it(self):
        html = ('<p>앞 문단 설명</p><img class="se-image-resource" src="https://x/blur" '
                'data-lazy-src="https://postfiles.pstatic.net/a.png?type=w773"/><p>뒤 문단</p>'
                '<img class="se-oglink-thumbnail-resource" src="https://dthumb-phinf.pstatic.net/?src=y"/>'
                '<img src="https://e.com/face.jpg" width="100"/>')
        seen = {}

        def fake(items, **kw):
            seen["items"] = items
            return {items[0]["key"]: NOTE}
        with patch.object(ir, "read_images", side_effect=fake):
            md = to_markdown(self.doc(html))
        self.assertEqual(md, f"앞 문단 설명\n\n{NOTE}\n\n뒤 문단")   # 문단처럼 빈 줄 하나로 구분
        self.assertEqual(len(seen["items"]), 1)                       # 링크 미리보기·작은 이미지는 사전 필터
        it = seen["items"][0]
        self.assertEqual(it["url"], "https://postfiles.pstatic.net/a.png?type=w773")   # lazy 원본 우선
        self.assertEqual(it["referer"], "https://blog.naver.com/")
        self.assertIn("앞 문단 설명", it["context"])
        self.assertIn("뒤 문단", it["context"])

    def test_unread_image_leaves_no_trace(self):
        with patch.object(ir, "read_images", return_value={}):
            md = to_markdown(self.doc('<p>a</p><img src="https://e.com/c.png"/><p>b</p>'))
        self.assertEqual(md, "a\n\nb")


class ReadImagesTests(unittest.TestCase):
    def setUp(self):
        self.f = tempfile.NamedTemporaryFile(suffix=".db")
        conn = self.connect()
        conn.executescript("""
            CREATE TABLE image_readings (image_key TEXT PRIMARY KEY, status TEXT NOT NULL, kind TEXT, title TEXT,
                insight TEXT, evidence TEXT, events_json TEXT, attempts INTEGER NOT NULL DEFAULT 0, error TEXT,
                model TEXT, updated_at TEXT DEFAULT (datetime('now')));""")
        conn.close()
        self.patches = [patch.object(ir, "get_connection", side_effect=self.connect),
                        patch.object(ir, "_in_scope", return_value=True),
                        patch.object(ir, "_load", return_value=(b"x", "png"))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.f.close()

    def connect(self):
        c = sqlite3.connect(self.f.name)
        c.row_factory = sqlite3.Row
        return c

    def items(self, n):
        return [{"key": f"k{i}", "url": f"https://e.com/{i}.png", "context": "글"} for i in range(n)]

    def test_doc_is_atomic_when_budget_short(self):
        with patch.object(ir, "_remaining_budget", return_value=2), patch.object(ir, "_call") as call:
            out = ir.read_images(self.items(3), published_at="", source="s")
        call.assert_not_called()
        self.assertEqual(out, {"k0": None, "k1": None, "k2": None})

    def test_reads_caches_and_formats(self):
        ans = {"kind": "chart", "skip": False, "title": "DRAM 수출 단가", "insight": "급등했다.", "evidence": "68,000"}
        with patch.object(ir, "_remaining_budget", return_value=30), \
             patch.object(ir, "_call", return_value=ans) as call:
            out = ir.read_images(self.items(1), published_at="", source="s")
            again = ir.read_images(self.items(1), published_at="", source="s")
        self.assertEqual(call.call_count, 1)                           # 두 번째는 캐시
        self.assertEqual(out["k0"], "[이미지 해석·AI · 차트] DRAM 수출 단가 — 급등했다. (근거: 68,000)")
        self.assertEqual(again, out)

    def test_offline_is_not_counted_as_attempt(self):
        import requests
        bf = ir.Backfill(calls_left=10, deadline=10**12)
        with patch.object(ir, "_load", side_effect=requests.ConnectionError("NameResolutionError")), \
             patch.object(ir, "_online", return_value=False), ir.backfill_mode(bf):
            ir.read_images(self.items(2), published_at="", source="s")
        self.assertTrue(bf.offline)
        self.assertEqual(bf.calls_left, 10)                              # LLM을 부르지 않았다
        self.assertEqual(ir.unresolved(["k0", "k1"]), 2)                 # 기록 없음 → 다음 회차에 다시

    def test_dead_host_while_online_counts_as_failure(self):
        import requests
        with patch.object(ir, "_remaining_budget", return_value=30), \
             patch.object(ir, "_load", side_effect=requests.ConnectionError("x")), \
             patch.object(ir, "_online", return_value=True):
            ir.read_images(self.items(1), published_at="", source="s")
        conn = self.connect()
        self.assertEqual(conn.execute("SELECT status, attempts FROM image_readings").fetchone()[:], ("failed", 1))

    def test_skip_and_failure_retry_cap(self):
        with patch.object(ir, "_remaining_budget", return_value=30), \
             patch.object(ir, "_call", side_effect=[{"kind": "photo", "skip": True, "insight": "밈"}]):
            self.assertEqual(ir.read_images(self.items(1), published_at="", source="s"), {"k0": None})
        with patch.object(ir, "_remaining_budget", return_value=30), \
             patch.object(ir, "_call", side_effect=RuntimeError("boom")) as call:
            for _ in range(5):
                ir.read_images([{"key": "bad", "url": "u"}], published_at="", source="s")
        self.assertEqual(call.call_count, ir.MAX_ATTEMPTS)


class TelegramTests(unittest.TestCase):
    def test_notes_go_after_their_message_and_raw_stays_original(self):
        from pipeline.connectors import telegram as tg
        msgs = [{"message_id": "10", "date": "2026-10-23T00:00:00+00:00", "content": "첫 글", "link": "L",
                 "images": ["https://cdn/a.jpg"]},
                {"message_id": "11", "date": "2026-10-23T00:00:30+00:00", "content": "", "images": ["https://cdn/b.jpg"]}]
        notes = {"telegram/ch_10_0": NOTE, "telegram/ch_11_0": None}
        with patch.object(tg, "scrape_channel", return_value=msgs), \
             patch.object(tg, "group_bursts", return_value=[msgs]), \
             patch.object(tg.image_reading, "read_images", side_effect=lambda items, **kw: notes) as ri:
            [doc] = tg.TelegramConnector(["ch"]).fetch(tg.SourceRef(key="ch"))
        self.assertEqual(doc.raw_content, "첫 글")
        self.assertEqual(doc.markdown, f"첫 글\n\n{NOTE}")
        self.assertEqual({i["context"] for i in ri.call_args.args[0]}, {"첫 글"})

    def test_image_only_post_keeps_image_title(self):
        from pipeline.connectors import telegram as tg
        msgs = [{"message_id": "7", "date": "2026-10-23T00:00:00+00:00", "content": "", "images": ["https://cdn/a.jpg"]}]
        with patch.object(tg, "scrape_channel", return_value=msgs), \
             patch.object(tg, "group_bursts", return_value=[msgs]), \
             patch.object(tg.image_reading, "read_images", return_value={"telegram/ch_7_0": NOTE}):
            [doc] = tg.TelegramConnector(["ch"]).fetch(tg.SourceRef(key="ch"))
        self.assertEqual((doc.title, doc.raw_content, doc.markdown), ("[이미지] ch #7", "", NOTE))


class StripTests(unittest.TestCase):
    def test_ai_lines_removed_for_author_only_paths(self):
        from pipeline import doc_claims
        text = f"저자의 문장이 충분히 길게 이어져서 인용 후보가 된다.\n{NOTE} 이 해석 줄도 충분히 길다."
        self.assertEqual(ir.strip_ai_notes(text), "저자의 문장이 충분히 길게 이어져서 인용 후보가 된다.")
        self.assertEqual(doc_claims._sentences(text), ["저자의 문장이 충분히 길게 이어져서 인용 후보가 된다."])



class BackfillTests(unittest.TestCase):
    def test_apply_carries_tags_to_new_hash(self):
        from pipeline import image_backfill as ib
        f = tempfile.NamedTemporaryFile(suffix=".db")
        conn = sqlite3.connect(f.name)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE raw_documents (id INTEGER PRIMARY KEY, markdown TEXT, content_hash TEXT);
            CREATE TABLE enrichments (doc_id INTEGER, content_hash TEXT, model TEXT, UNIQUE(doc_id, content_hash));
            CREATE TABLE image_backfill_docs (doc_id INTEGER PRIMARY KEY, done_at TEXT);
            INSERT INTO raw_documents VALUES (1, '글', 'old');
            INSERT INTO enrichments VALUES (1, 'old', 'haiku');""")
        r = conn.execute("SELECT * FROM raw_documents WHERE id=1").fetchone()
        self.assertTrue(ib._apply(conn, r, f"글\n\n{NOTE}"))
        h = conn.execute("SELECT content_hash FROM raw_documents").fetchone()[0]
        self.assertEqual(conn.execute("SELECT content_hash FROM enrichments").fetchone()[0], h)   # 재태깅 없이 이월
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM image_backfill_docs").fetchone()[0], 1)
        f.close()

    def test_db_lock_ends_run_as_partial(self):
        from pipeline import image_backfill as ib
        row = {"id": 1, "source_type": "blog", "source_id": "u", "title": "", "url": "", "published_at": "",
               "raw_content": "<p>a</p>", "markdown": "a", "content_hash": "h", "media_json": None}
        with patch.object(ib, "_candidates", side_effect=[[row], [], []]), \
             patch.object(ib, "_blog_md", side_effect=sqlite3.OperationalError("database is locked")), \
             patch.object(ib, "get_connection", side_effect=lambda: self.fake_conn()):
            out = ib.run(calls=5, minutes=1)
        self.assertEqual((out["stopped"], out["status"]), ("locked", "partial"))

    def fake_conn(self):
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE raw_documents (id INTEGER, published_at TEXT, source_type TEXT, media_json TEXT)")
        c.execute("CREATE TABLE image_backfill_docs (doc_id INTEGER)")
        return c

    def test_old_telegram_notes_go_to_end_in_image_order(self):
        from pipeline import image_backfill as ib
        r = {"raw_content": "본문"}
        self.assertEqual(ib._telegram_md(r, ["a", "b"], {"a": None, "b": NOTE}), f"본문\n\n{NOTE}")
        self.assertEqual(ib._telegram_md({"raw_content": ""}, ["a"], {"a": NOTE}), NOTE)


if __name__ == "__main__":
    unittest.main()
