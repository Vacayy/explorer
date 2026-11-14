"""품목 벽 일괄 API `GET /api/spine/trade/grid` (D-325, 산업 › 수출입 품목 모니터).

세목 제외 · 기간 24/60개월 · 12개월 평균 · 판정 · 관련 종목 코드 — 원본은 한 번만 읽는다(품목마다 조회하지 않는다).
"""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from pipeline import trade_metrics
from routers import spine_trade
from tests.test_trade_hygiene import TradeDbCase, _months


class TradeGridTests(TradeDbCase):
    def setUp(self):
        super().setUp()
        self.conn.executemany("INSERT INTO trade_follow(hs_code, item_name, group_label) VALUES (?,?,?)", [
            ("854232", "메모리", "반도체"), ("8542321010", "D램", "반도체"), ("2710", "석유제품", "에너지")])
        rows = []
        for i, p in enumerate(_months(72)):
            k = 3.0 if i == 71 else 1 + 0.02 * (i % 5)
            rows += [("854232", p, 100e6 * k), ("8542321010", p, 60e6 * k)]
            if i != 70:                                   # 석유는 전달이 빈다 — 격자에는 null로 남는다
                rows.append(("2710", p, 50e6))
        self.conn.executemany("INSERT INTO trade_stats(hs_code, period, export_usd) VALUES (?,?,?)", rows)
        self.conn.execute("INSERT INTO trade_beneficiaries VALUES ('854232','000660','SK하이닉스','수혜','메모리 수출')")
        self.conn.execute("INSERT INTO trade_beneficiaries VALUES ('854232','005930','삼성전자','수혜','메모리 수출')")

    def get(self, months=None):
        q = "" if months is None else f"?months={months}"
        with patch.object(trade_metrics, "get_connection", return_value=self.conn), \
                patch.object(spine_trade, "get_connection", return_value=self.conn), \
                patch.object(trade_metrics, "raw_series", side_effect=AssertionError("품목마다 따로 읽지 않는다")):
            return TestClient(app).get(f"/api/spine/trade/grid{q}")

    def test_top_level_items_with_series_ma_and_verdict(self):
        r = self.get()
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["months"], 24)
        self.assertEqual(d["period"], "2029-12")
        by = {i["hs_code"]: i for i in d["items"]}
        self.assertEqual(set(by), {"854232", "2710"})                 # 세목(D램) 제외
        mem = by["854232"]
        self.assertEqual(len(mem["series"]), 24)
        self.assertEqual(mem["series"][-1]["period"], "2029-12")
        self.assertEqual(mem["flag"], "surge")
        self.assertEqual(mem["stock_codes"], ["000660", "005930"])
        self.assertAlmostEqual(mem["latest_export"], 300e6)
        last12 = [p["export_usd"] for p in mem["series"][-12:]]
        self.assertAlmostEqual(mem["series"][-1]["ma12"], sum(last12) / 12)
        oil = by["2710"]
        self.assertIsNone(oil["series"][-2]["export_usd"])           # 빈 달
        self.assertIsNone(oil["series"][-2]["ma12"])
        self.assertEqual(oil["stock_codes"], [])

    def test_five_years_and_invalid_months(self):
        self.assertEqual(len(self.get(60).json()["items"][0]["series"]), 60)
        self.assertEqual(self.get(30).status_code, 422)


if __name__ == "__main__":
    unittest.main()
