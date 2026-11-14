"""섹터 지도 · 섹터 화면 (ia-redesign §4.35, D-327) — 대표지수·계산 지수·내러티브 연결·산업 개괄 생성 규칙과 API 모양.

- 대표지수 대응표는 코드 SEED가 원본: init마다 맞추고, ETF가 없는 섹터는 ticker NULL(화면은 계산 지수라고 밝힌다).
- 계산 지수: 최신 주식 수 고정 시총 가중 체인, 가격을 가진 종목 비중이 COVERAGE 이상인 첫날 = 100.
- 장중에 수집하면 오늘 봉(장중 값)은 버린다.
- 내러티브 연결: 섹터 고유 키워드를 먼저, 같으면 그 섹터 · 아니면 topic 안에서 가장 앞에 나오는 키워드의 섹터.
- 산업 개괄: 내러티브가 같으면 건너뛰고, 바뀌어도 7일 안이면 건너뛴다.
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import database
from main import app
from pipeline import sector_benchmarks as sb
from pipeline import sector_overview as so
from pipeline import sector_view as sv


class TmpDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch.object(database, "DB_PATH", Path(self.tmp.name) / "t.db").start()
        self.addCleanup(patch.stopall)
        database.init_db()
        self.conn = database.get_connection()
        self.addCleanup(self.conn.close)


class BenchmarkSeedTests(TmpDb):
    def test_seed_covers_18_sectors_and_is_idempotent(self):
        rows = {r["sector"]: dict(r) for r in self.conn.execute("SELECT * FROM sector_benchmarks")}
        self.assertEqual(len(rows), 18)
        self.assertEqual(rows["반도체·전자부품"]["ticker"], "091160")
        self.assertEqual(rows["반도체·전자부품"]["tracks"], "KRX 반도체")
        self.assertIsNone(rows["통신"]["ticker"])
        self.assertTrue(rows["통신"]["note"])
        self.assertEqual(sb.seed(self.conn), 0)

    def test_every_etf_has_name_and_index_and_computed_has_reason(self):
        for sector, ticker, name, tracks, note in sb.SEED:
            if ticker:
                self.assertRegex(ticker, r"^\d{6}$", sector)
                self.assertTrue(name and tracks, sector)
            else:
                self.assertTrue(note, sector)
                self.assertIsNone(name)

    def test_collect_drops_intraday_bar_and_reports_failures(self):
        now = datetime(2026, 11, 6, 4, 0, tzinfo=timezone.utc)      # 13:00 KST — 장중
        calls = []

        def fetch(symbol, days):
            calls.append(symbol)
            if symbol == "091160.KS":
                raise RuntimeError("boom")
            return [("2026-11-05", 100.0), ("2026-11-06", 90.0)]
        out = sb.collect(self.conn, fetch=fetch, now=now)
        self.assertIn("^KS11", calls)
        self.assertIn("091160(RuntimeError)", out["degraded"])
        dates = {r[0] for r in self.conn.execute("SELECT DISTINCT trade_date FROM sector_benchmark_prices")}
        self.assertEqual(dates, {"2026-11-05"})
        after_close = datetime(2026, 11, 6, 7, 0, tzinfo=timezone.utc)   # 16:00 KST
        self.assertEqual(sb._closed_through(after_close), "2026-11-06")


class ChainIndexTests(unittest.TestCase):
    def test_cap_weighted_chain_with_fixed_shares(self):
        prices = {"A": {"d1": 100, "d2": 110, "d3": 110}, "B": {"d1": 50, "d2": 50, "d3": 25}}
        weights = {"A": 300.0, "B": 100.0}          # 최신 시총 → 주식 수 A 2.727…, B 4
        latest = {"A": 110, "B": 25}
        out = dict(sb.chain_index(prices, weights, latest))
        self.assertEqual(out["d1"], 100.0)
        # d2: A 시총(전날) 272.7, B 200 → (272.7×10% + 0) / 472.7
        self.assertAlmostEqual(out["d2"], 100 * (1 + 27.2727 / 472.7273), places=2)

    def test_starts_when_coverage_reached(self):
        prices = {"A": {"d2": 10, "d3": 11}, "B": {"d1": 10, "d2": 10, "d3": 10}}
        out = sb.chain_index(prices, {"A": 90.0, "B": 10.0}, {"A": 11, "B": 10})
        self.assertEqual(out[0], ("d2", 100.0))      # d1은 B(10%)만 → 60% 미만이라 건너뜀


class TopicSectorTests(unittest.TestCase):
    primary = {"반도체·전자부품": {"반도체", "전자부품", "메모리"}, "기계·장비": {"기계", "장비", "로봇"},
               "항공·방산·우주": {"방산", "우주"}}
    themes = {"반도체·전자부품": {"HBM", "DRAM"}, "기계·장비": {"반도체 장비"}, "항공·방산·우주": set()}

    def check(self, topic):
        return sv.topic_sectors(topic, self.primary, self.themes)

    def test_exact_and_earliest_contained_keyword(self):
        self.assertEqual(self.check("메모리"), {"반도체·전자부품"})
        self.assertEqual(self.check("추론 전환과 메모리 재평가"), {"반도체·전자부품"})
        self.assertEqual(self.check("반도체 장비"), {"반도체·전자부품"})   # 고유 키워드가 테마보다 먼저
        self.assertEqual(self.check("우주항공"), {"항공·방산·우주"})

    def test_themes_only_when_primary_misses_and_no_match_is_empty(self):
        self.assertEqual(self.check("HBM"), {"반도체·전자부품"})
        self.assertEqual(self.check("금리"), set())


class OverviewRuleTests(TmpDb):
    def test_due_rules(self):
        now = datetime(2026, 11, 10, tzinfo=timezone.utc)
        self.assertIsNone(so._due(None, "h", now))
        self.assertEqual(so._due({"input_hash": "h", "generated_at": "2026-10-01 00:00:00"}, "h", now), "내러티브 변화 없음")
        self.assertEqual(so._due({"input_hash": "x", "generated_at": "2026-11-08 00:00:00"}, "h", now), "주 1회 상한")
        self.assertIsNone(so._due({"input_hash": "x", "generated_at": "2026-11-01 00:00:00"}, "h", now))

    def test_clean_requires_question_and_three_bullets(self):
        self.assertEqual(so.clean({"question": "질문", "bullets": ["a", "b", "c"]}), ("질문", ["a", "b", "c"]))
        self.assertIsNone(so.clean({"question": "질문", "bullets": ["a"]}))
        self.assertIsNone(so.clean(None))

    def test_run_writes_once_then_skips_without_change(self):
        self.conn.execute("INSERT INTO sector_map (sector_name, group_name) VALUES ('반도체', '반도체·전자부품')")
        self.conn.execute("INSERT INTO narratives (topic, version, title) VALUES ('반도체', 1, '메모리 부족이 길어집니다')")
        self.conn.commit()
        calls = []

        def call(text):
            calls.append(text)
            return {"question": "부족이 길어지는가?", "bullets": ["하나", "둘", "셋"]}
        now = datetime(2026, 11, 6, tzinfo=timezone.utc)
        out = so.run(["반도체·전자부품", "통신"], now=now, call=call)
        self.assertEqual(out["made"], ["반도체·전자부품"])
        self.assertEqual(out["skipped"]["통신"], "연결된 내러티브 없음")
        self.assertIn("메모리 부족이 길어집니다", calls[0])
        again = so.run(["반도체·전자부품"], now=now, call=call)
        self.assertEqual(again["skipped"]["반도체·전자부품"], "내러티브 변화 없음")
        self.assertEqual(len(calls), 1)
        row = sv.overview_row(self.conn, "반도체·전자부품")
        self.assertEqual(row["bullets"], ["하나", "둘", "셋"])


class ApiShapeTests(TmpDb):
    """빈 DB에서도 모양이 맞고, 없는 섹터는 404."""

    def setUp(self):
        super().setUp()
        sv._cache.clear()
        from pipeline import sector_rs
        sector_rs._cache.clear()
        self.client = TestClient(app)

    def test_map_on_empty_db(self):
        r = self.client.get("/api/spine/industry/map")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sectors"], [])

    def test_unknown_sector_404(self):
        self.assertEqual(self.client.get("/api/spine/industry/없는섹터").status_code, 404)


if __name__ == "__main__":
    unittest.main()
