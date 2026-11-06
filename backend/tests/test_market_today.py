"""Market Today: 회차 창, 같은 얘기 묶기, 인용 검증·정렬, 건너뛰기·저장 (docs/specs/market-today.md)."""
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from pipeline import market_today as mt

BASE = """
CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, source_type TEXT, source_id TEXT, title TEXT, url TEXT, published_at TEXT, markdown TEXT);
CREATE TABLE telegram_channels(channel_name TEXT, display_name TEXT);
CREATE TABLE macro_news(url TEXT, feed TEXT, publisher TEXT, kind TEXT, title TEXT, summary TEXT, published_at TEXT, fetched_at TEXT);
CREATE TABLE stock_prices(stock_code TEXT, trade_date TEXT);
"""


class MarketTodayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "t.sqlite"
        conn = self.connect()
        conn.executescript(BASE + mt.SCHEMA)
        conn.executemany("INSERT INTO telegram_channels VALUES (?,?)", [("a", "채널A"), ("b", "채널B"), ("c", "채널C")])
        conn.execute("INSERT INTO stock_prices VALUES ('005930', '2026-10-30')")   # 전 거래일 = 금요일
        docs = [  # 11/3(화) 11:30~15:00 KST = 02:30~06:00 UTC
            (1, "a/1", "WSJ - 미국, 이란 케슘섬 공습…트럼프는 전쟁 재개 가능성 축소", "2026-11-03T04:10:00+00:00", "WSJ - 미국, 이란 케슘섬 공습…트럼프는 전쟁 재개 가능성 축소. 유가 반응은 제한적"),
            (2, "b/7", "WSJ - 미국, 이란 케슘섬 공습…트럼프는 전쟁 재개 가능성 축소", "2026-11-03T04:12:00+00:00", "WSJ - 미국, 이란 케슘섬 공습…트럼프는 전쟁 재개 가능성 축소"),
            (3, "c/2", "대만 팀그룹: 메모리 공급 부족 2028년 하반기까지 지속 전망", "2026-11-03T05:00:00+00:00", "대만 팀그룹: 메모리 공급 부족 2028년 하반기까지 지속 전망. 4분기 30~40% 가격 상승"),
            (4, "a/2", "2026.11.03 15:51:58", "2026-11-03T05:30:00+00:00", "채널 공지입니다. 오늘 장 마감 후 라이브 방송을 합니다 많관부"),
            (5, "a/3", "어제 글", "2026-11-03T02:29:00+00:00", "11:30 이전 글 — 이 회차 창 밖이라 빠져야 한다"),
        ]
        conn.executemany("INSERT INTO raw_documents (id, source_type, source_id, title, url, published_at, markdown) VALUES (?,'telegram',?,?,NULL,?,?)",
                         [(i, sid, t, p, m) for i, sid, t, p, m in docs])
        conn.execute("INSERT INTO macro_news VALUES ('u1','f','Bloomberg','news','Oil Slumps on Iran Peace Talk Hopes','',"
                     "'2026-11-03T04:30:00+00:00','2026-11-03T04:31:00+00:00')")
        conn.commit()
        conn.close()
        p = patch.object(mt, "get_connection", self.connect)
        p.start()
        self.addCleanup(p.stop)

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_windows_start_at_previous_slot_and_first_slot_at_previous_trading_close(self):
        conn = self.connect()
        self.assertEqual(mt.window(conn, date(2026, 11, 3), "1500"), ("2026-11-03T02:30:00+00:00", "2026-11-03T06:00:00+00:00"))
        # 월요일 09:30 회차는 금요일 16:00 마감 정리부터 — 주말 사이 소식이 빠지지 않게
        self.assertEqual(mt.window(conn, date(2026, 11, 2), "0930")[0], "2026-10-30T07:00:00+00:00")
        # 16:00 마감 정리는 그날 09:00부터 하루 전체
        self.assertEqual(mt.window(conn, date(2026, 11, 3), "1600"), ("2026-11-03T00:00:00+00:00", "2026-11-03T07:00:00+00:00"))
        conn.close()

    def test_due_slot_is_latest_passed_and_none_on_weekend_or_before_open(self):
        utc = lambda kst_h, kst_m, d=3: datetime(2026, 11, d, kst_h - 9, kst_m, tzinfo=timezone.utc)
        self.assertEqual(mt.due_slot(utc(14, 5)), (date(2026, 11, 3), "1130"))
        self.assertEqual(mt.due_slot(utc(16, 1)), (date(2026, 11, 3), "1600"))
        self.assertIsNone(mt.due_slot(utc(9, 29)))
        self.assertIsNone(mt.due_slot(datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc)))   # 일요일

    def test_gather_groups_reposts_and_counts_distinct_publishers(self):
        conn = self.connect()
        sources, counts = mt.gather(conn, *mt.window(conn, date(2026, 11, 3), "1500"))
        conn.close()
        self.assertEqual(counts, {"telegram": 4, "news": 1}, "창 밖(13:00 이전) 글은 빠진다")
        iran = next(s for s in sources if "케슘섬" in s["title"])
        self.assertEqual((iran["echo"], iran["publishers"]), (2, ["채널A", "채널B"]))
        self.assertEqual(sources[0]["ref"], "S1")
        self.assertIs(sources[0], iran, "같은 얘기를 다룬 출처가 많은 묶음이 앞")

    def test_verify_keeps_only_quotes_found_verbatim_and_orders_by_echo(self):
        conn = self.connect()
        sources, _ = mt.gather(conn, *mt.window(conn, date(2026, 11, 3), "1500"))
        conn.close()
        ref = {("이란" if "케슘섬" in s["title"] else "메모리" if "팀그룹" in s["title"] else s["title"]): s["ref"] for s in sources}
        raw = [
            {"title": "메모리 공급 부족 장기화", "body": "…", "tags": ["메모리"], "sources": [{"ref": ref["메모리"], "quote": "메모리 공급 부족 2028년 하반기까지 지속 전망"}]},
            {"title": "지어낸 화두", "body": "…", "sources": [{"ref": ref["메모리"], "quote": "원문에 없는 인용 문장입니다"}]},
            {"title": "미국, 이란 케슘섬 공습", "body": "…", "continuing": True, "sources": [{"ref": ref["이란"], "quote": "이란 케슘섬 공습…트럼프는 전쟁 재개"}]},
        ]
        topics = mt.verify(raw, sources)
        self.assertEqual([t["title"] for t in topics], ["미국, 이란 케슘섬 공습", "메모리 공급 부족 장기화"], "인용이 틀린 화두는 버리고 언급 출처 수 순")
        self.assertEqual(topics[0]["echo"], 2)
        self.assertTrue(topics[0]["continuing"])

    def test_run_stores_once_skips_without_force_and_skips_thin_windows(self):
        conn = self.connect()
        sources, _ = mt.gather(conn, *mt.window(conn, date(2026, 11, 3), "1500"))
        conn.close()
        iran = next(s for s in sources if "케슘섬" in s["title"])["ref"]
        fake = lambda prompt: {"topics": [{"title": "미국, 이란 케슘섬 공습", "body": "WSJ 보도입니다.", "tags": ["이란"],
                                            "sources": [{"ref": iran, "quote": "미국, 이란 케슘섬 공습"}]}]}
        snap = lambda d, s: {"kospi": {"value": 5648.79, "change_pct": -3.59, "at": "15:30"}, "path": [["09:00", 5702.5]]}
        r = mt.run(date(2026, 11, 3), "1500", call=fake, check_holiday=False, snapshot=snap)
        self.assertEqual((r["status"], r["topics"]), ("ok", 1))
        self.assertEqual(mt.run(date(2026, 11, 3), "1500", call=fake, check_holiday=False, snapshot=snap)["status"], "exists")
        d = mt.read("2026-11-03")
        self.assertEqual(d["current"]["topics"][0]["sources"][0]["publisher"], "채널A")
        self.assertEqual([s["label"] for s in d["slots"]], ["15:00"])
        self.assertEqual(d["current"]["market"]["kospi"]["change_pct"], -3.59, "회차 시점 시장 상태를 함께 쌓는다")
        self.assertEqual(mt.run(date(2026, 11, 3), "0930", call=fake, check_holiday=False, snapshot=snap)["status"], "skipped", "자료가 적은 창은 만들지 않는다")

    def test_wrap_slot_sees_whole_day_and_all_intraday_topics(self):
        snap = lambda d, s: None
        fake = lambda prompt: {"topics": []}
        conn = self.connect()
        conn.execute("INSERT INTO market_today (trade_date, slot, window_start, window_end, items_json, sources_json, doc_count) "
                     "VALUES ('2026-11-03','0930','a','b',?, '{}', 9), ('2026-11-03','1130','a','b',?, '{}', 9)",
                     ('[{"title": "아침 화두"}]', '[{"title": "점심 화두"}]'))
        conn.commit()
        conn.close()
        seen = []
        mt.run(date(2026, 11, 3), "1600", call=lambda p: seen.append(p) or {"topics": []}, check_holiday=False, snapshot=snap)
        self.assertIn("오늘 하루", seen[0])
        self.assertIn("아침 화두", seen[0], "마감 정리는 그날 장중 회차 화두를 전부 본다")
        self.assertIn("점심 화두", seen[0])
        self.assertIn("11:30 이전 글", seen[0], "창 = 09:00부터 하루 전체")
        seen.clear()
        mt.run(date(2026, 11, 3), "1500", call=lambda p: seen.append(p) or {"topics": []}, check_holiday=False, snapshot=snap)
        self.assertNotIn("아침 화두", seen[0], "장중 회차는 직전 회차만")
        self.assertEqual(mt.read("2026-11-03")["slots"][-1]["label"], "16:00 마감")

    def test_read_defaults_to_today_kst_and_navigates_days(self):
        conn = self.connect()
        for d in ("2026-11-02", "2026-11-04"):
            conn.execute("INSERT INTO market_today (trade_date, slot, window_start, window_end, items_json, sources_json, doc_count) "
                         "VALUES (?, '1600', 'a', 'b', '[]', '{}', 5)", (d,))
        conn.commit()
        conn.close()
        from unittest.mock import patch as _p
        class _DT(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 11, 5, 23, 40, tzinfo=timezone.utc)   # KST 11/6 08:40 — 자정 넘어 다음 날
        with _p.object(mt, "datetime", _DT):
            r = mt.read()
        self.assertEqual((r["trade_date"], r["slots"], r["current"]), ("2026-11-06", [], None), "자정이 지나면 오늘(회차 전)로")
        self.assertEqual((r["prev_date"], r["next_date"]), ("2026-11-04", None))
        with _p.object(mt, "datetime", _DT):
            r = mt.read("2026-11-04")
        self.assertEqual((r["prev_date"], r["next_date"], r["next_slot"]), ("2026-11-02", "2026-11-06", None))


if __name__ == "__main__":
    unittest.main()


class MarketSnapshotPrevCloseTests(unittest.TestCase):
    """yfinance 일봉이 전일을 빠뜨려도(2026-11-06 실측: 11/5 누락) 저장된 종가로 전일 대비를 낸다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "t.sqlite"
        conn = self.connect()
        conn.execute("CREATE TABLE market_indicators(snapshot_date TEXT, indicator TEXT, value REAL, fetched_at TEXT)")
        conn.executemany("INSERT INTO market_indicators VALUES (?,?,?,'')",
                         [("2026-11-04", "index_kospi", 5683.8), ("2026-11-05", "index_kospi", 5383.8)])
        conn.commit()
        conn.close()
        p = patch.object(mt, "get_connection", self.connect)
        p.start()
        self.addCleanup(p.stop)

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _fake_yf(self):
        import sys
        import types
        import pandas as pd
        kst = "Asia/Seoul"
        daily = pd.Series([5683.8, 4966.28], index=pd.to_datetime(["2026-11-04", "2026-11-06"]).tz_localize(kst))
        bars = pd.Series([4923.47], index=pd.DatetimeIndex([pd.Timestamp("2026-11-06 09:10", tz=kst)]))

        class T:
            def __init__(self, tk): self.tk = tk
            def history(self, period, interval=None):
                return pd.DataFrame({"Close": bars if interval else daily})
        return patch.dict(sys.modules, {"yfinance": types.SimpleNamespace(Ticker=T)})

    def test_prev_close_comes_from_stored_indicators_when_yfinance_daily_skips_a_day(self):
        with self._fake_yf():
            snap = mt.market_snapshot(date(2026, 11, 6), "0930")
        self.assertEqual(snap["kospi"]["value"], 4923.47)
        self.assertEqual(snap["kospi"]["change_pct"], -8.55)       # 11/5 5383.8 대비 (11/4 대비면 −13.38)
        self.assertEqual(snap["kosdaq"]["change_pct"], -13.38)    # 저장분이 없으면 yfinance 일봉으로 (가짜 시세는 같은 값)
