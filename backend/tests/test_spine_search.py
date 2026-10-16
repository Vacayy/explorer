"""통합 검색: 순위(정확·접두·시총), 미국 티커, 묶음 포함 표시, 오늘 신호 (D-189)."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import watch_rules as wr
from routers import spine_search

SCHEMA = """
CREATE TABLE companies(corp_code TEXT, corp_name TEXT, stock_code TEXT, market TEXT, sector TEXT);
CREATE TABLE stock_prices(stock_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, market_cap REAL, shares REAL);
CREATE TABLE transcript_follow(ticker TEXT, company_name TEXT, entity_id INTEGER, group_label TEXT, active INTEGER, added_at TEXT);
CREATE TABLE us_fundamentals(ticker TEXT, data_json TEXT, fetched_at TEXT);
CREATE TABLE entities(id INTEGER PRIMARY KEY, type TEXT, name TEXT, aliases TEXT, meta_json TEXT, status TEXT DEFAULT 'active');
CREATE TABLE study_projects(id INTEGER PRIMARY KEY, title TEXT, updated_at TEXT);
CREATE TABLE entity_keywords(id INTEGER PRIMARY KEY, entity_id INTEGER, keyword TEXT);
"""


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "db.sqlite"
        conn = self.connect()
        conn.executescript(SCHEMA + wr.SCHEMA)
        conn.executemany("INSERT INTO companies VALUES (?,?,?,?,?)", [
            ("c1", "삼성수산", "052560", "KOSDAQ", "음식료"), ("c2", "삼성전자", "005930", "KOSPI", "반도체"),
            ("c3", "삼성물산", "028260", "KOSPI", "지주"), ("c4", "한화에어로스페이스", "012450", "KOSPI", "방산"), ("c5", "우리삼성", "999990", "KOSDAQ", "기타")])
        for code, cap, closes in (("052560", 3e11, (1000, 1010)), ("005930", 1.5e15, (250000, 259000)), ("028260", 3.6e13, (150000, 149000)), ("999990", 1e11, (500, 500))):
            for day, close in zip(("2026-09-17", "2026-09-18"), closes):
                conn.execute("INSERT INTO stock_prices VALUES (?,?,?,?,?,?,?,?,?)", (code, day, close, close, close, close, 100, cap, 1))
        conn.execute("INSERT INTO transcript_follow VALUES ('NVDA','NVIDIA',1,'AI 반도체',1,'2026-01-01')")
        conn.execute("INSERT INTO us_fundamentals VALUES ('MSTR','{}','2026-09-13')")
        conn.execute("INSERT INTO entities (type, name) VALUES ('person','이재용'), ('theme','HBM'), ('theme','전자'), ('company','이닉스'), ('company','SK하이닉스')")
        conn.execute("INSERT INTO entities (type, name, aliases) VALUES ('company','삼성전자','005930'), ('company','한화에어로스페이스','012450')")
        conn.execute("INSERT INTO entity_keywords (entity_id, keyword) SELECT id, 'Samsung' FROM entities WHERE name='삼성전자'")
        conn.execute("INSERT INTO study_projects (title, updated_at) VALUES ('삼성 메모리 스터디', '2026-09-19')")
        gid = conn.execute("INSERT INTO stock_groups (name, kind) VALUES ('관심 종목','watch')").lastrowid
        conn.execute("INSERT INTO stock_group_members (group_id, stock_code) VALUES (?, '005930')", (gid,))
        rid = conn.execute("INSERT INTO watch_rules (group_id, strategy_id, params_json) VALUES (?, 'volume_increase', '{}')", (gid,)).lastrowid
        conn.execute("INSERT INTO watch_evaluations (group_id, stock_code, rule_id, as_of, status) VALUES (?, '005930', ?, '2026-09-17', 'fail')", (gid, rid))
        conn.execute("INSERT INTO watch_evaluations (group_id, stock_code, rule_id, as_of, status) VALUES (?, '005930', ?, '2026-09-18', 'pass')", (gid, rid))
        conn.commit(); conn.close()
        patch.object(spine_search, "get_connection", self.connect).start()
        patch.object(wr, "connect", self.connect).start()
        self.addCleanup(patch.stopall)
        app = FastAPI(); app.include_router(spine_search.router); self.client = TestClient(app)

    def connect(self):
        conn = sqlite3.connect(self.path); conn.row_factory = sqlite3.Row
        return conn

    def test_prefix_matches_rank_by_market_cap_and_carry_context(self):
        body = self.client.get("/api/spine/search", params={"q": "삼성"}).json()
        names = [c["name"] for c in body["companies"]]
        self.assertEqual(names, ["삼성전자", "삼성물산", "삼성수산", "우리삼성"], "prefix matches first, market cap order, then contains")
        first = body["companies"][0]
        self.assertEqual((first["market"], first["sector"], first["close"], first["in_groups"]), ("KOSPI", "반도체", 259000, ["관심 종목"]))
        self.assertAlmostEqual(first["change_pct"], 3.6)
        self.assertEqual(body["groups"][0]["name"], "관심 종목", "a group containing a top match is offered")
        self.assertEqual(body["projects"][0]["title"], "삼성 메모리 스터디")
        self.assertEqual([e["name"] for e in body["entities"]], [], "company entities are not duplicated as people/themes")

    def test_exact_code_and_us_tickers(self):
        by_code = self.client.get("/api/spine/search", params={"q": "005930"}).json()
        self.assertEqual(by_code["companies"][0]["name"], "삼성전자")
        us = self.client.get("/api/spine/search", params={"q": "nv"}).json()["us"]
        self.assertEqual(us[0], {"ticker": "NVDA", "name": "NVIDIA", "group_label": "AI 반도체"})
        self.assertEqual([u["ticker"] for u in self.client.get("/api/spine/search", params={"q": "MS"}).json()["us"]], ["MSTR"], "fundamentals-only tickers are searchable too")
        self.assertEqual([e["name"] for e in self.client.get("/api/spine/search", params={"q": "HBM"}).json()["entities"]], ["HBM"])
        self.assertEqual(self.client.get("/api/spine/search", params={"q": ""}).status_code, 422)

    def test_choseong_alias_and_sentence_mentions(self):
        cho = self.client.get("/api/spine/search", params={"q": "ㅅㅅㅈㅈ"}).json()
        self.assertTrue(cho["choseong"])
        self.assertEqual([c["name"] for c in cho["companies"]], ["삼성전자"], "initial consonants match the company name")
        self.assertEqual([c["name"] for c in self.client.get("/api/spine/search", params={"q": "ㅅㅅ"}).json()["companies"]][:2], ["삼성전자", "삼성물산"], "prefix hits keep market-cap order")
        alias = self.client.get("/api/spine/search", params={"q": "Samsung"}).json()["companies"]
        self.assertEqual([(c["name"], c["alias"]) for c in alias], [("삼성전자", "Samsung")], "entity keyword aliases resolve to the company")
        sentence = self.client.get("/api/spine/search", params={"q": "이재용 회장이 삼성전자 HBM 투자를 늘린다는데 한화에어로스페이스·SK하이닉스와 비교해줘"}).json()
        self.assertEqual([(m["name"], m["type"], m["stock_code"]) for m in sentence["mentions"]],
                         [("한화에어로스페이스", "company", "012450"), ("SK하이닉스", "company", None), ("삼성전자", "company", "005930"), ("이재용", "person", None), ("HBM", "theme", None)],
                         "fragments inside longer names (이닉스) and two-letter generic themes (전자) are dropped")
        self.assertEqual(self.client.get("/api/spine/search", params={"q": "삼성"}).json()["mentions"], [], "short single words are not scanned for mentions")

    def test_today_lists_new_signals_on_latest_evaluation_day(self):
        body = self.client.get("/api/spine/search/today").json()
        self.assertEqual(body["as_of"], "2026-09-18")
        self.assertEqual([(i["name"], i["strategy_id"], i["group_name"]) for i in body["items"]], [("삼성전자", "volume_increase", "관심 종목")])


if __name__ == "__main__":
    unittest.main()
