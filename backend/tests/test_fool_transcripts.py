"""Motley Fool 녹취록 수집 (D-218) — 네트워크 없이 고르기·본문 자르기만."""
import unittest

from pipeline import fool_transcripts as ft

PAGE = """<html><script>x</script><h2>Full Conference Call Transcript</h2><p>Operator: Good afternoon.</p>
""" + "".join(f"<p>Speaker {i}: We grew revenue. {'x' * 400}</p>" for i in range(12)) + """<p>Operator: This concludes today's conference call.</p>
<h3>Read Next</h3><p>Oct 12 • 4 No-Brainer Chip Stocks</p></html>"""


class FoolTests(unittest.TestCase):
    def test_extract_cuts_boilerplate(self):
        body = ft.extract(PAGE)
        self.assertTrue(body.startswith("Operator: Good afternoon."))
        self.assertTrue(body.rstrip().endswith("This concludes today's conference call."))
        self.assertNotIn("No-Brainer", body)
        self.assertIsNone(ft.extract("<p>layout changed</p>"))      # 못 찾으면 엉뚱한 본문을 저장하지 않는다
        host = PAGE.replace("Operator:", "Ana Soro:")                # 진행자가 Operator가 아닌 콜(PLTR)도 받는다
        self.assertTrue(ft.extract(host).startswith("Ana Soro: Good afternoon."))

    def test_pick_prefers_label_then_date_window(self):
        links = [{"url": "a", "date": "2026-08-31", "label": (2027, 2)}, {"url": "b", "date": "2026-05-20", "label": None},
                 {"url": "c", "date": "2026-03-01", "label": None}]
        self.assertEqual(ft.pick(links, 2027, 2, "2026-08-26")["url"], "a")     # 게시일이 5일 늦어도 라벨로
        self.assertEqual(ft.pick(links, 2027, 1, "2026-05-20")["url"], "b")     # 라벨 없으면 날짜 창
        self.assertIsNone(ft.pick(links, 2026, 4, "2026-02-01"))                 # 창(−2~+10일) 밖


if __name__ == "__main__":
    unittest.main()
