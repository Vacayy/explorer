"""미국장 브리핑 매크로 문단 (D-206): 인용 검증, 출처 표식 재번호, 금리 bp, 시간창."""
import sqlite3
import unittest

from pipeline import us_briefing as ub

SOURCES = [
    {"ref": "T1", "kind": "telegram", "publisher": "YIELD & SPREAD", "title": "금리",
     "url": "https://t.me/yieldnspread/1", "doc_id": 11, "published_at": "2026-09-28T21:00:00+00:00",
     "text": "미 10년물 금리는  5.2%를 넘어섰고\n입찰 수요가 약했다."},
    {"ref": "N1", "kind": "news", "publisher": "Bloomberg", "title": "Gold Trades Near Seven-Week Low",
     "url": "https://bloomberg.example/gold", "doc_id": None, "published_at": "2026-09-29T00:02:41+00:00",
     "text": "Gold Trades Near Seven-Week Low as Rate-Hike Pressure Mounts\nGold held a sharp decline as the deadlock between the US and…"},
]


class VerifyIssuesTests(unittest.TestCase):
    def test_keeps_exact_quote_after_whitespace_normalization(self):
        raw = [{"title": "금리 상승", "what": "…", "sources": [{"ref": "T1", "quote": "금리는 5.2%를 넘어섰고 입찰 수요가"}]}]
        self.assertEqual(ub._verify_issues(raw, SOURCES)[0]["refs"], ["T1"])

    def test_curly_apostrophes_match_straight(self):
        src = [{**SOURCES[1], "text": "Fed’s Waller says cuts are off the table"}]
        raw = [{"title": "연준", "sources": [{"ref": "N1", "quote": "Fed's Waller says cuts"}]}]
        self.assertEqual(len(ub._verify_issues(raw, src)), 1)

    def test_drops_paraphrased_or_unknown_sources(self):
        raw = [{"title": "금", "sources": [{"ref": "N1", "quote": "금 가격이 7주 저점"},     # 번역 — 원문에 없음
                                           {"ref": "N9", "quote": "Gold Trades Near"}]}]   # 없는 ref
        self.assertEqual(ub._verify_issues(raw, SOURCES), [])

    def test_partial_verification_keeps_only_verified_refs(self):
        raw = [{"title": "금", "sources": [{"ref": "N1", "quote": "Rate-Hike Pressure Mounts"},
                                           {"ref": "T1", "quote": "지어낸 문장입니다"}]}]
        self.assertEqual(ub._verify_issues(raw, SOURCES)[0]["refs"], ["N1"])

    def test_non_list_input(self):
        self.assertEqual(ub._verify_issues(None, SOURCES), [])


class CitationTests(unittest.TestCase):
    ISSUES = {"issues": [{"title": "a", "refs": ["T1", "N1"]}, {"title": "b", "refs": ["N1"]}],
              "sources": {"T1": {"kind": "telegram", "publisher": "Y", "url": "u1"},
                          "N1": {"kind": "news", "publisher": "B", "url": "u2"}}}

    def test_renumbers_by_first_appearance_and_drops_unknown(self):
        (text,), sources = ub._link_citations(["금이 내렸다 [S2]. 금리가 올랐다 [S1][S2]. 없는 번호 [S7]."], self.ISSUES)
        self.assertEqual(text, "금이 내렸다[1]. 금리가 올랐다[2][1]. 없는 번호.")
        self.assertEqual([(s["n"], s["url"]) for s in sources], [(1, "u2"), (2, "u1")])

    def test_comma_list_marker(self):
        (text,), sources = ub._link_citations(["둘 다 [S1, S2]."], self.ISSUES)
        self.assertEqual(text, "둘 다[1][2].")
        self.assertEqual(len(sources), 2)

    def test_numbering_shared_across_paragraphs(self):
        texts, sources = ub._link_citations(["매크로 [S2].", "기업 [S1] 그리고 [S2]."], self.ISSUES)
        self.assertEqual(texts, ["매크로[1].", "기업[2] 그리고[1]."])
        self.assertEqual(len(sources), 2)

    def test_no_issues_leaves_text(self):
        self.assertEqual(ub._link_citations(["지표만."], {"issues": []}), (["지표만."], []))


class RateBpTests(unittest.TestCase):
    def test_bp_not_percent(self):
        bp = ub._rate_bp({"series": [5.10, 5.12, 5.15, 5.16, 5.18, 5.18, 5.24]})
        self.assertEqual(bp, {"last": 6.0, "short": 12.0})

    def test_short_series(self):
        self.assertEqual(ub._rate_bp({"series": [5.18, 5.24]}), {"last": 6.0, "short": None})
        self.assertIsNone(ub._rate_bp({"series": [5.24]}))


class WindowTests(unittest.TestCase):
    def conn(self, dates):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute("CREATE TABLE us_movers (trade_date TEXT)")
        c.executemany("INSERT INTO us_movers VALUES (?)", [(d,) for d in dates])
        return c

    def test_monday_starts_at_friday_close(self):
        self.assertEqual(ub._macro_window(self.conn(["2026-09-25", "2026-09-28"]), "2026-09-28"),
                         ("2026-09-25T20:00:00+00:00", "2026-09-29T00:00:00+00:00"))

    def test_no_previous_snapshot_falls_back_one_day(self):
        self.assertEqual(ub._macro_window(self.conn([]), "2026-09-28")[0], "2026-09-27T20:00:00+00:00")

    def test_long_gap_capped(self):
        self.assertEqual(ub._macro_window(self.conn(["2026-09-10"]), "2026-09-28")[0], "2026-09-24T20:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
