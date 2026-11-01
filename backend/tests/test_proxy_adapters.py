"""프록시 보드 어댑터 (D-240) — 원천 테이블에서 값·as_of(원천 날짜)·변화를 바르게 읽는가. 수치는 모두 가상 값."""
import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import database
from pipeline import proxy_adapters as pa
from pipeline import sector_rs

TODAY = date.today()


def day(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


class AdapterTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "t.sqlite"
        with patch.object(database, "DB_PATH", path):
            database.init_db()
        self.c = sqlite3.connect(path)
        self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        pa._memo.clear()

    def ins(self, sql, rows):
        self.c.executemany(sql, rows)
        self.c.commit()

    # credit — 스프레드 = ytm − 그날 국채 곡선 보간(credit_spreads.spread_series 재사용)
    def test_credit_spread_value_change_and_source_date(self):
        maturity = (TODAY + timedelta(days=365 * 5)).isoformat()
        self.ins("INSERT INTO credit_bonds (ticker, symbol, maturity) VALUES (?,?,?)", [("ORCL", "X:ORCL", maturity), ("META", "X:META", maturity)])
        self.ins("INSERT INTO treasury_curve (date, tenor, yield) VALUES (?,?,?)", [(day(n), t, 4.0) for n in (45, 3) for t in (1, 10)])
        self.ins("INSERT INTO credit_quotes (symbol, date, ytm) VALUES (?,?,?)",
                 [("X:ORCL", day(40), 6.0), ("X:ORCL", day(3), 7.0), ("X:META", day(40), 5.0), ("X:META", day(3), 5.0)])
        snap = pa.snapshot(self.c, "credit:ORCL")
        self.assertEqual(snap["latest"]["value"], 300.0)
        self.assertEqual(snap["latest"]["as_of"], day(3))          # 원천 날짜, 오늘이 아니다
        self.assertEqual(snap["latest"]["change"], 100.0)
        self.assertEqual(snap["latest"]["direction"], "up")
        self.assertEqual(snap["latest"]["unit"], "bp")
        self.assertEqual(pa.latest(self.c, "credit:group:hyperscaler")["value"], 200.0)   # (300 + 100) / 2
        refs = {e["ref"] for e in pa.catalog(self.c, "credit")}
        self.assertIn("credit:ORCL", refs)
        self.assertNotIn("credit:MSFT", refs)                      # 채권 원천이 없는 회사는 카탈로그에 없다
        self.assertIsNone(pa.describe(self.c, "credit:MSFT"))

    # trade — 수출 YoY는 trade_metrics.derive 재사용, 날짜는 'YYYY-MM' 원천 그대로
    def test_trade_value_and_yoy(self):
        self.ins("INSERT INTO trade_follow (hs_code, item_name, group_label) VALUES (?,?,?)", [("854232", "메모리", "반도체")])
        months = [f"{y}-{m:02d}" for y in (2025, 2026) for m in range(1, 13)][:14]   # 2025-01 .. 2026-02
        self.ins("INSERT INTO trade_stats (hs_code, period, export_usd, import_usd) VALUES (?,?,?,?)",
                 [("854232", p, 100.0 if p < "2026" else 150.0, 10.0) for p in months])
        value = pa.latest(self.c, "trade:854232")
        self.assertEqual((value["value"], value["as_of"], value["change"], value["change_basis"]), (150.0, "2026-02", 0.0, "전월"))
        yoy = pa.latest(self.c, "trade:854232:yoy")
        self.assertEqual((yoy["value"], yoy["unit"], yoy["change_pct"]), (50.0, "%", None))
        self.assertEqual(pa.describe(self.c, "trade:854232:yoy")["label"], "메모리 수출 YoY")
        self.assertIsNone(pa.describe(self.c, "trade:854232:bogus"))
        self.assertIsNone(pa.describe(self.c, "trade:999999"))

    # indicator — risk_*는 정본 정제 + bp 환산, risk_curve = (10Y−2Y)×100, 동기화 행·레거시는 카탈로그 밖
    def test_indicator_risk_scaling_curve_and_catalog(self):
        rows = [(day(35), "risk_hy", 3.0), (day(2), "risk_hy", 3.25), (day(2), "risk_us10y", 5.0), (day(2), "risk_us2y", 4.6),
                (day(1), "risk_sync_hy", None), (day(2), "vix", 20.0), (day(2), "macro_dxy", 101.5)]
        self.ins("INSERT INTO market_indicators (snapshot_date, indicator, value) VALUES (?,?,?)", rows)
        hy = pa.latest(self.c, "indicator:risk_hy")
        self.assertEqual((hy["value"], hy["as_of"], hy["change"], hy["unit"]), (325.0, day(2), 25.0, "bp"))
        self.assertAlmostEqual(pa.latest(self.c, "indicator:risk_curve")["value"], 40.0)
        refs = {e["ref"] for e in pa.catalog(self.c, "indicator")}
        self.assertTrue({"indicator:risk_hy", "indicator:risk_curve", "indicator:macro_dxy"} <= refs)
        self.assertFalse({"indicator:risk_sync_hy", "indicator:vix"} & refs)
        self.assertIsNone(pa.describe(self.c, "indicator:nope"))

    # retail — retail_heat.computed 재사용. 백분위는 이력 2년 미만이면 비어 '원천 없음'
    def test_retail_metric_and_missing_percentile(self):
        self.ins("INSERT INTO retail_flows (date, forced_sales, credit_total) VALUES (?,?,?)",
                 [(day(60 - i), 10.0, 1000.0) for i in range(60)])
        f = pa.latest(self.c, "retail:forced_20")
        self.assertEqual((f["value"], f["as_of"], f["unit"]), (200.0, day(1), "KRW"))
        self.assertIsNone(pa.describe(self.c, "retail:forced_20_pct"))
        self.assertIsNotNone(pa.describe(self.c, "retail:forced_20"))

    # call_momentum — 시즌별 기업 수, 진행 중 시즌은 직전 시즌 같은 경과 시점과 비교
    def test_call_momentum_season_counts(self):
        raised = json.dumps({"drivers": [{"name": "AI accelerator demand", "status": "new"}],
                             "guidance": [{"metric": "revenue", "direction": "raised"}, {"metric": "capex", "direction": "raised"}]})
        flat = json.dumps({"drivers": [], "guidance": [{"metric": "revenue", "direction": "maintained"}]})
        self.ins("INSERT INTO call_momentum (ticker, event_date, score, status, reasons) VALUES (?,?,?,?,?)", [
            ("AAA", "2026-07-05", 9, "candidate", raised),    # 2분기 시즌(7-01 시작) 5일차
            ("BBB", "2026-07-20", 3, "none", raised),         # 2분기 시즌 20일차 — 같은 경과 시점 밖
            ("CCC", "2026-10-04", 9, "candidate", raised),    # 3분기 시즌 4일차
            ("DDD", "2026-10-06", 1, "none", flat),
        ])
        g = pa.latest(self.c, "call_momentum:guidance_raised_count")
        self.assertEqual((g["value"], g["as_of"]), (1.0, "2026-10-06"))
        self.assertEqual(g["change"], 0.0)                     # 직전 시즌 6일차까지는 AAA 1곳
        self.assertEqual(g["change_basis"], "직전 시즌 같은 시점(5일차)")
        self.assertEqual(pa.series(self.c, "call_momentum:guidance_raised_count", "2026-01-01"), [("2026-07-20", 2.0), ("2026-10-06", 1.0)])
        self.assertEqual(pa.latest(self.c, "call_momentum:capex_raised_count")["value"], 1.0)
        self.assertEqual(pa.latest(self.c, "call_momentum:ai_driver_count")["value"], 1.0)
        self.assertEqual(pa.latest(self.c, "call_momentum:CCC")["value"], 9.0)
        self.assertIsNone(pa.describe(self.c, "call_momentum:ZZZ"))

    def test_price_close_and_change_pct(self):
        self.ins("INSERT INTO companies (corp_code, corp_name, stock_code) VALUES (?,?,?)", [("1", "삼성전자", "005930")])
        self.ins("INSERT INTO stock_prices (stock_code, trade_date, close) VALUES (?,?,?)", [("005930", day(40), 100), ("005930", day(1), 110)])
        p = pa.latest(self.c, "price:005930")
        self.assertEqual((p["value"], p["as_of"], p["change"], p["change_pct"]), (110.0, day(1), 10.0, 10.0))
        self.assertEqual(pa.catalog(self.c, "price", q="삼성")[0]["ref"], "price:005930")

    def test_sector_reuses_sector_map_trail(self):
        self.ins("INSERT INTO sector_map (sector_name, group_name) VALUES (?,?)", [("반도체 제조업", "반도체·전자부품")])
        fake = {"as_of": "2026-10-16", "groups": [{"name": "반도체·전자부품", "rs_short": 20, "rs_long": 80,
                "trail": [{"weeks_ago": 1, "rs_short": 40, "rs_long": 82}, {"weeks_ago": 2, "rs_short": 50, "rs_long": 85},
                          {"weeks_ago": 3, "rs_short": 60, "rs_long": 85}]}]}
        with patch.object(sector_rs, "compute_sector_map", return_value=fake):
            s = pa.latest(self.c, "sector:반도체·전자부품")
            self.assertEqual((s["value"], s["as_of"], s["change"], s["change_basis"]), (20.0, "2026-10-16", -40.0, "3주 전"))
            self.assertEqual(pa.latest(self.c, "sector:반도체·전자부품:rs_long")["value"], 80.0)
        self.assertIsNone(pa.describe(self.c, "sector:없는섹터"))

    def test_existing_proxy_observations(self):
        self.ins("INSERT INTO proxy_registry (id, key, label, unit, modality) VALUES (?,?,?,?,?)",
                 [(1, "capex", "CAPEX", "$B", "numeric"), (2, "mood", "여론", None, "sentiment")])
        self.ins("INSERT INTO proxy_observations (proxy_id, observed_at, value_num, direction, source_type) VALUES (?,?,?,?,?)",
                 [(1, "2026-07-01", 20.0, "up", "transcript"), (1, "2026-09-10", 28.0, "up", "transcript"),
                  (2, "2026-09-01", None, "up", "corpus"), (2, "2026-09-02", None, "down", "corpus")])
        t = pa.latest(self.c, "transcript:1")
        self.assertEqual((t["value"], t["as_of"], t["change"]), (28.0, "2026-09-10", 8.0))
        s = pa.latest(self.c, "corpus:2")
        self.assertEqual((s["value"], s["direction"]), (-1.0, "down"))
        self.assertIsNone(pa.describe(self.c, "corpus:1"))      # numeric 프록시는 corpus가 아니다

    def test_parse_rejects_unknown(self):
        self.assertIsNone(pa.parse("nope:1"))
        self.assertIsNone(pa.parse("credit"))
        self.assertEqual(pa.parse("ORCL", "credit"), ("credit", "ORCL"))
        self.assertIsNone(pa.parse("trade:854232", "credit"))


if __name__ == "__main__":
    unittest.main()
