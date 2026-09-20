"""DART 정기보고서 '사업의 내용' 확보: 최신 보고서 선택, 절 추출, 저장 재사용 (D-188 후속)."""
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from pipeline import dart_business as db


class FakeDart:
    def __init__(self):
        self.calls = []

    def list(self, corp, start, end, kind):
        self.calls.append(("list", corp, kind))
        return pd.DataFrame([{"rcept_no": "20260907000191", "report_nm": "주식등의대량보유상황보고서(약식)", "rcept_dt": "20260907"},
                             {"rcept_no": "20260814004015", "report_nm": "반기보고서 (2026.06)", "rcept_dt": "20260814"},
                             {"rcept_no": "20260319000776", "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260319"}])

    def sub_docs(self, rcept_no):
        self.calls.append(("sub_docs", rcept_no))
        return pd.DataFrame([{"title": "I. 회사의 개요", "url": "http://dart.fss.or.kr/report/viewer.do?eleId=3"},
                             {"title": "1. 사업의 개요", "url": "http://dart.fss.or.kr/report/viewer.do?eleId=10"},
                             {"title": "2. 주요 제품 및 서비스", "url": "http://dart.fss.or.kr/report/viewer.do?eleId=11"},
                             {"title": "5. 위험관리 및 파생거래", "url": "http://dart.fss.or.kr/report/viewer.do?eleId=14"}])


PAGES = {"eleId=10": "<html><body><p>1. 사업의 개요</p><p>당사는 고압 수소 어닐링 장비를 연구·개발·제조·판매한다. " + "상세 설명 " * 20 + "</p></body></html>",
         "eleId=11": "<html><body><table><tr><td>2. 주요 제품 및 서비스</td></tr><tr><td>HPA 장비 매출 비중 95%</td></tr></table>" + "x " * 40 + "</body></html>"}


def fetch(url):
    return PAGES[url.split("?")[1]]


class DartBusinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.conn = sqlite3.connect(Path(self.tmp.name) / "db.sqlite"); self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""CREATE TABLE raw_documents(id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT, url TEXT,
            published_at TEXT, fetched_at TEXT DEFAULT (datetime('now')), raw_content TEXT, markdown TEXT, content_hash TEXT, UNIQUE(source_type, source_id));""")
        self.dart = FakeDart()

    def test_latest_periodic_report_skips_non_periodic_filings(self):
        report = db.latest_periodic_report(self.dart, "01288827", date(2026, 9, 20))
        self.assertEqual((report["rcept_no"], report["rcept_dt"]), ("20260814004015", "2026-08-14"))

    def test_sections_are_extracted_stored_once_and_reused(self):
        business = db.ensure_business_text(self.conn, "403870", "01288827", "HPSP", dart=self.dart, fetch=fetch, today=date(2026, 9, 20))
        self.assertEqual([s["key"] for s in business["sections"]], ["overview", "products"], "only business-content sections, no risk chapter")
        self.assertIn("고압 수소 어닐링", business["sections"][0]["text"])
        self.assertNotIn("<", business["sections"][0]["text"])
        rows = self.conn.execute("SELECT source_id, title, published_at FROM raw_documents ORDER BY id").fetchall()
        self.assertEqual([r["source_id"] for r in rows], ["403870:20260814004015:overview", "403870:20260814004015:products"])
        self.assertEqual(rows[0]["published_at"], "2026-08-14")
        again = db.ensure_business_text(self.conn, "403870", "01288827", "HPSP", dart=self.dart, fetch=fetch, today=date(2026, 9, 20))
        self.assertEqual(again["rcept_no"], "20260814004015")
        self.assertEqual([c for c in self.dart.calls if c[0] == "sub_docs"], [("sub_docs", "20260814004015")], "stored report is not fetched again")
        excerpt = db.official_excerpt(business, limit=200)
        self.assertTrue(excerpt.startswith("[1. 사업의 개요]"))
        self.assertLessEqual(len(excerpt), 260)

    def test_missing_report_or_sections_raise_unavailable(self):
        class Empty(FakeDart):
            def list(self, *a, **k): return pd.DataFrame([])
        with self.assertRaises(db.DartBusinessUnavailable):
            db.ensure_business_text(self.conn, "000001", "00000001", "X", dart=Empty(), fetch=fetch)
        with self.assertRaises(db.DartBusinessUnavailable):
            db.ensure_business_text(self.conn, "000002", "00000002", "Y", dart=self.dart, fetch=lambda url: "<html></html>", today=date(2026, 9, 20))


if __name__ == "__main__":
    unittest.main()
