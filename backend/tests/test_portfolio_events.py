"""포트폴리오 다가오는 이벤트 (portfolio-intelligence §4). DART는 가짜."""
import sqlite3
import unittest
from datetime import date

from pipeline import portfolio_events as pe

TODAY = date(2026, 10, 8)
H = [{"code": "000001", "name": "가"}, {"code": "000002", "name": "나"}]


class FakeDart:
    def __init__(self, filings, docs):
        self.filings, self.docs, self.opened = filings, docs, 0

    def list(self, corp, start, end):
        import pandas as pd
        rows = [f for f in self.filings.get(corp, []) if start <= f["rcept_dt"] <= end]
        return pd.DataFrame(rows) if rows else None

    def document(self, rcp):
        self.opened += 1
        return self.docs[rcp]


def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(pe.SCHEMA + """CREATE TABLE catalysts (id INTEGER PRIMARY KEY, stock_code TEXT, corp_code TEXT, event_type TEXT,
        event_date TEXT, title TEXT, description TEXT, created_at TEXT);
        CREATE TABLE transcript_calendar (ticker TEXT, next_report_date TEXT);
        INSERT INTO transcript_calendar VALUES ('MU','2026-10-20'),('XXX','2026-10-21');""")
    return c


class EventTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(pe.parse_event("1. 일시 및 장소 일시 2025-10-29 09:00 장소 - 3. 개최목적 2025년 3분기 경영실적 발표 4. 기타"),
                         ("2025-10-29", "2025년 3분기 경영실적 발표"))
        self.assertEqual(pe.parse_event("공시예정일 2025-11-07 4. 기타")[0], "2025-11-07")
        self.assertEqual(pe.parse_event("일시 날짜 2026년 9월 4일 시간")[0], "2026-09-04")

    def test_windows_split_long_ranges(self):
        w = list(pe._windows(TODAY, 120))
        self.assertEqual(w[0][1], "20261008")
        self.assertTrue(all(len(x) == 2 for x in w) and len(w) == 4)

    def test_confirmed_then_estimate_skips(self):
        c = db()
        dart = FakeDart({"C1": [{"rcept_dt": "20261001", "report_nm": "기업설명회(IR)개최(안내공시)", "rcept_no": "20261001000001"}],
                         "C2": [{"rcept_dt": "20251107", "report_nm": "연결재무제표기준영업(잠정)실적(공정공시)", "rcept_no": "x"}]},
                        {"20261001000001": "일시 2026-10-22 09:00 개최목적 3분기 경영실적 발표 4."})
        corp = {"000001": "C1", "000002": "C2"}.get
        self.assertEqual(pe.collect_confirmed(c, H, TODAY, dart, corp), 1)
        pe.collect_confirmed(c, H, TODAY, dart, corp)
        self.assertEqual(dart.opened, 1)                                      # 읽은 접수번호는 다시 안 연다
        pe.estimate(c, H, TODAY, dart, corp)
        ev = pe.upcoming(c, H, {"반도체·전자부품"}, TODAY)
        got = [(e["date"], e["kind"], e["estimated"]) for e in ev]
        self.assertIn(("2026-10-22", "ir", False), got)                       # 확정이 있으면 가 종목은 예상치 없음
        self.assertIn(("2026-11-06", "earnings_est", True), got)              # 작년 11-07 + 364
        self.assertIn(("2026-10-20", "us_earnings", False), got)              # 체인 대표 해외 기업만
        self.assertNotIn("XXX", str(ev))

    def test_deadline_when_no_preliminary_history(self):
        c = db()
        pe.estimate(c, H[:1], TODAY, FakeDart({}, {}), lambda code: "C1")
        r = c.execute("SELECT event_date, kind FROM portfolio_event_estimates").fetchone()
        self.assertEqual(tuple(r), ("2026-11-14", "report_deadline"))


if __name__ == "__main__":
    unittest.main()
