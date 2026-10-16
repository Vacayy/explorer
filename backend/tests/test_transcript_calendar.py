"""실적 발표일 캐시(transcript_calendar) — 조회 실패가 기존 발표일을 지우지 않는다.

2026-10-13 22:24 DNS 장애로 팔로우 113개 조회가 모두 실패했는데, 실패한 종목에도 (NULL, NULL, 지금)을
덮어써 발표일이 사라지고 '방금 확인함'으로 찍혀 다음 갱신(24시간·7일 캐시)까지 다시 묻지 않았다.
"""
import sqlite3
import sys
import types
import unittest
from unittest import mock

import pandas as pd

from pipeline import transcript as tr


class _Conn:
    """refresh_calendar가 close()해도 메모리 DB가 남게"""
    def __init__(self, c): self.c = c
    def execute(self, *a): return self.c.execute(*a)
    def commit(self): self.c.commit()
    def close(self): pass


def _db():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE transcript_calendar (ticker TEXT PRIMARY KEY, last_report_date TEXT, "
              "next_report_date TEXT, checked_at TEXT)")
    c.execute("INSERT INTO transcript_calendar VALUES ('AAPL','2026-07-30','2026-10-29','2026-10-01 00:00:00')")
    return c


def _fake_yf(behavior):
    class T:
        def __init__(self, tk): self.tk = tk
        def get_earnings_dates(self, limit=8): return behavior(self.tk)
    return types.SimpleNamespace(Ticker=T)


def _frame(rows):
    idx = pd.DatetimeIndex([pd.Timestamp(d, tz="America/New_York") for d, _ in rows], name="Earnings Date")
    return pd.DataFrame({"Reported EPS": [e for _, e in rows]}, index=idx)


class CalendarTests(unittest.TestCase):
    def run_refresh(self, c, behavior, tickers):
        with mock.patch.object(tr, "get_connection", lambda: _Conn(c)), \
             mock.patch.dict(sys.modules, {"yfinance": _fake_yf(behavior)}):
            return tr.refresh_calendar(tickers, max_age_hours=0)

    def test_failure_keeps_previous_dates_and_check_time(self):
        c = _db()
        def boom(tk): raise RuntimeError("curl: (6) Could not resolve host: query1.finance.yahoo.com")
        n = self.run_refresh(c, boom, ["AAPL"])
        self.assertEqual(n, 0)
        row = c.execute("SELECT last_report_date, next_report_date, checked_at FROM transcript_calendar").fetchone()
        self.assertEqual(row, ("2026-07-30", "2026-10-29", "2026-10-01 00:00:00"))

    def test_network_outage_stops_early(self):
        c = _db()
        calls = []
        def boom(tk):
            calls.append(tk)
            raise RuntimeError("Could not resolve host")
        self.run_refresh(c, boom, [f"T{i}" for i in range(40)])
        self.assertLess(len(calls), 40)
        self.assertEqual(c.execute("SELECT count(*) FROM transcript_calendar").fetchone()[0], 1)

    def test_success_writes_last_and_next(self):
        c = _db()
        df = _frame([("2099-11-17 16:00", float("nan")), ("2026-08-26 16:00", 2.22), ("2026-05-20 16:00", 1.87)])
        n = self.run_refresh(c, lambda tk: df, ["NVDA"])
        self.assertEqual(n, 1)
        row = c.execute("SELECT last_report_date, next_report_date FROM transcript_calendar WHERE ticker='NVDA'").fetchone()
        self.assertEqual(row, ("2026-08-26", "2099-11-17"))


if __name__ == "__main__":
    unittest.main()
