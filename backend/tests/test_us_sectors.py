"""미국 섹터 지도 · 섹터 화면 (ia-redesign §4.36) — ETF 대응·RS 백분위·커버리지 묶기·끝나지 않은 미국 장 버리기·API 모양.

- 섹터 = GICS 11 + 세부 업종 13 ETF, 비교 SPY. RS는 국내와 같은 창(장기 91일 · 단기 7일)의 24개 간 백분위.
- 팔로우 종목은 Yahoo sector → GICS ETF, industry → 세부 업종 ETF. 세부 업종의 상위가 GICS와 다르면 세부는 버린다.
- GICS ETF의 커버리지는 그 섹터 전부(세부 업종 포함), 세부 업종 ETF는 그 업종만.
- 뉴욕 16:10 전에 돌면 그날 봉(장중 값)은 저장하지 않는다.
"""
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

import database
from main import app
from pipeline import us_sectors as us


class RuleTests(unittest.TestCase):
    def test_etf_mapping(self):
        self.assertEqual(us.etf_of("Technology", "Semiconductors"), ("XLK", "SMH"))
        self.assertEqual(us.etf_of("Technology", "Semiconductor Equipment & Materials"), ("XLK", "SMH"))
        self.assertEqual(us.etf_of("Technology", "Consumer Electronics"), ("XLK", None))
        self.assertEqual(us.etf_of("Energy", "Uranium"), ("XLE", "URA"))
        # 세부 업종 ETF의 상위(XLK)가 Yahoo sector의 GICS(XLC)와 다르면 세부는 버린다
        self.assertEqual(us.etf_of("Communication Services", "Software - Application"), ("XLC", None))
        self.assertEqual(us.etf_of(None, None), (None, None))

    def test_every_map_target_is_a_known_etf(self):
        self.assertEqual(len(us.ETFS), 24)
        self.assertEqual(sum(1 for *_, p in us.ETFS if p is None), 11)
        for etf in [*us.SECTOR_ETF.values(), *us.INDUSTRY_ETF.values()]:
            self.assertIn(etf, us.META)
        for *_, p in us.ETFS:
            self.assertTrue(p is None or us.META[p]["parent"] is None)
        self.assertEqual(sorted(us.wall_order()), sorted(us.TICKERS))
        self.assertEqual(us.wall_order()[:4], ["XLK", "SMH", "IGV", "CIBR"])

    def test_percentile_over_calendar_windows(self):
        days = [(date(2026, 8, 1) + timedelta(days=i)).isoformat() for i in range(100)]
        # A: 꾸준히 오름, B: 평평, C: 꾸준히 내림 + 마지막 주에 급반등
        a = [(d, 100 + i) for i, d in enumerate(days)]
        b = [(d, 100.0) for d in days]
        c = [(d, 200 - i if i < 93 else 108 + (i - 92) * 5) for i, d in enumerate(days)]
        rs = us.rs_at({"A": a, "B": b, "C": c}, days[-1])
        self.assertEqual(rs["A"]["rs_long"], 100)
        self.assertEqual(rs["C"]["rs_long"], 0)
        self.assertEqual(rs["B"]["rs_long"], 50)
        self.assertEqual(rs["C"]["rs_short"], 100)
        self.assertEqual(rs["B"]["rs_short"], 0)
        # 기준일이 주말·휴장이면 그 전 마지막 종가
        self.assertEqual(us.on_or_before(a, "2030-01-01"), a[-1][1])
        self.assertIsNone(us.on_or_before(a, "2020-01-01"))

    def test_zone(self):
        self.assertEqual(us.zone(80, 60), "주도")
        self.assertEqual(us.zone(80, 10), "숨 고르기")
        self.assertEqual(us.zone(10, 60), "반등 시도")
        self.assertEqual(us.zone(10, 10), "소외")
        self.assertIsNone(us.zone(None, 10))

    def test_member_grouping_and_coverage(self):
        fol = [{"ticker": "NVDA", "gics": "XLK", "sub": "SMH", "market_cap": 5e12},
               {"ticker": "MSFT", "gics": "XLK", "sub": "IGV", "market_cap": 4e12},
               {"ticker": "AAPL", "gics": "XLK", "sub": None, "market_cap": 4.5e12},
               {"ticker": "AMD", "gics": "XLK", "sub": "SMH", "market_cap": 3e11},
               {"ticker": "XOM", "gics": "XLE", "sub": None, "market_cap": None},
               {"ticker": "ZZZ", "gics": None, "sub": None, "market_cap": 1}]
        self.assertEqual([m["ticker"] for m in us.members_of("XLK", fol)], ["NVDA", "AAPL", "MSFT", "AMD"])
        self.assertEqual([m["ticker"] for m in us.members_of("SMH", fol)], ["NVDA", "AMD"])
        self.assertEqual(us.members_of("XLV", fol), [])
        self.assertEqual(us.coverage_counts(fol), {"XLK": 4, "SMH": 2, "IGV": 1, "XLE": 1})

    def test_closed_through_drops_unfinished_us_session(self):
        # 2026-11-06(금) 15:00 뉴욕 = 장중 → 목요일까지
        self.assertEqual(us.closed_through(datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)), "2026-11-05")
        # 16:30 뉴욕(한국 토요일 06:30) → 금요일까지
        self.assertEqual(us.closed_through(datetime(2026, 11, 6, 21, 30, tzinfo=timezone.utc)), "2026-11-06")
        # 한국 16:55(뉴욕 02:55) → 전날까지
        self.assertEqual(us.closed_through(datetime(2026, 11, 6, 7, 55, tzinfo=timezone.utc)), "2026-11-05")


def _frame(symbols, dates, close=lambda s, i: 100 + i):
    cols = pd.MultiIndex.from_product([["Close", "Open", "High", "Low", "Volume"], symbols])
    idx = pd.DatetimeIndex(dates)
    data = {(f, s): [close(s, i) for i in range(len(dates))] for f, s in cols}
    return pd.DataFrame(data, index=idx, columns=cols)


class TmpDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch.object(database, "DB_PATH", Path(self.tmp.name) / "t.db").start()
        self.addCleanup(patch.stopall)
        database.init_db()
        self.conn = database.get_connection()
        self.addCleanup(self.conn.close)


class CollectTests(TmpDb):
    def test_collect_etfs_drops_unfinished_session_and_reports_missing(self):
        now = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)      # 뉴욕 금요일 15:00 — 장중
        dates = ["2026-11-04", "2026-11-05", "2026-11-06"]
        calls = []

        def download(syms, start, adjust):
            calls.append((len(syms), start, adjust))
            return _frame([s for s in syms if s != "URA"], dates)

        r = us.collect_etfs(self.conn, download=download, now=now)
        self.assertEqual(calls, [(25, (date(2026, 11, 6) - timedelta(days=us.BACKFILL_DAYS)).isoformat(), True)])
        self.assertEqual(r["degraded"], ["URA"])
        self.assertEqual(self.conn.execute("SELECT max(trade_date) FROM sector_benchmark_prices WHERE ticker='SPY'").fetchone()[0], "2026-11-05")
        self.assertEqual(r["rows"], 24 * 2)

    def test_collect_sectors_only_missing_or_stale(self):
        self.conn.executemany("INSERT INTO transcript_follow (ticker, company_name, active) VALUES (?, ?, ?)",
                              [("NVDA", "NVIDIA", 1), ("AAPL", "Apple", 1), ("OLD", "Old", 0), ("MSFT", "Microsoft", 1)])
        self.conn.execute("INSERT INTO us_ticker_sectors VALUES ('AAPL', 'Technology', 'Consumer Electronics', datetime('now', '-3 days'))")
        self.conn.execute("INSERT INTO us_ticker_sectors VALUES ('MSFT', 'Technology', 'Software', datetime('now', '-40 days'))")
        asked = []

        def info(t):
            asked.append(t)
            return {"sector": "Technology", "industry": "Semiconductors" if t == "NVDA" else "Software - Infrastructure"}

        r = us.collect_sectors(self.conn, info=info, sleep=0)
        self.assertEqual(asked, ["MSFT", "NVDA"])
        self.assertEqual(r, {"due": 2, "fetched": 2, "failed": []})
        fol = {f["ticker"]: f for f in us.follows(self.conn)}
        self.assertEqual((fol["NVDA"]["gics"], fol["NVDA"]["sub"]), ("XLK", "SMH"))
        self.assertEqual((fol["MSFT"]["gics"], fol["MSFT"]["sub"]), ("XLK", "IGV"))
        self.assertEqual((fol["AAPL"]["gics"], fol["AAPL"]["sub"]), ("XLK", None))


class ApiTests(TmpDb):
    def test_map_and_detail_shapes(self):
        days = [(date(2026, 5, 1) + timedelta(days=i)).isoformat() for i in range(150)]
        rows = [(t, d, 100 + i * (1 + k / 10)) for k, t in enumerate(us.TICKERS + [us.SPY]) for i, d in enumerate(days)]
        self.conn.executemany("INSERT INTO sector_benchmark_prices VALUES (?, ?, ?)", rows)
        self.conn.execute("INSERT INTO transcript_follow (ticker, company_name, active, market_cap) VALUES ('NVDA', 'NVIDIA', 1, 5e12)")
        self.conn.execute("INSERT INTO us_ticker_sectors VALUES ('NVDA', 'Technology', 'Semiconductors', datetime('now'))")
        self.conn.executemany("INSERT INTO us_prices (stock_code, trade_date, close) VALUES ('NVDA', ?, ?)", [(d, 50 + i) for i, d in enumerate(days)])
        self.conn.commit()
        c = TestClient(app)
        m = c.get("/api/spine/industry/us/map").json()
        self.assertEqual(m["as_of"], days[-1])
        self.assertEqual(len(m["sectors"]), 24)
        self.assertEqual(len(m["spy"]), 61)
        smh = next(s for s in m["sectors"] if s["ticker"] == "SMH")
        self.assertEqual((smh["parent"], smh["coverage"], len(smh["trail"])), ("XLK", 1, 4))
        self.assertEqual(next(s for s in m["sectors"] if s["ticker"] == "XLK")["coverage"], 1)
        d = c.get("/api/spine/industry/us/smh").json()
        self.assertEqual(d["ticker"], "SMH")
        self.assertEqual(d["parent_name"], "기술")
        self.assertEqual([s["ticker"] for s in d["siblings"]], ["XLK", "SMH", "IGV", "CIBR"])
        self.assertEqual(d["members"][0]["ticker"], "NVDA")
        self.assertEqual(d["members"][0]["industry"], "반도체")
        self.assertEqual(len(d["members"][0]["closes"]), 64)
        self.assertEqual(len(d["series"]), 150)
        self.assertEqual(c.get("/api/spine/industry/us/NOPE").status_code, 404)

    def test_empty_db(self):
        c = TestClient(app)
        self.assertEqual(c.get("/api/spine/industry/us/map").json(), {"as_of": None, "spy": [], "sectors": []})
        self.assertEqual(c.get("/api/spine/industry/us/XLK").status_code, 200)


if __name__ == "__main__":
    unittest.main()
