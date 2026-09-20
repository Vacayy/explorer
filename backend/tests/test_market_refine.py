"""질문 다듬기: 카탈로그 검증, 항상 확인 항목, 문장 조립 (D-186)."""
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline.market_analysis import refine
from routers.analysis import router

RAW = {
    "restatement": "바닥을 찍고 반등을 시작한 종목을 찾는 질문으로 이해했습니다.",
    "conditions": [
        {"text": "20일 이동평균이 최근 5거래일 안에 상승 반전", "source": "바닥찍고 올라오는", "strategy_id": "sma_slope_up_20d",
         "params": {"period": 20}, "within_days": 5, "confidence": "low",
         "alternatives": [{"text": "5일 이동평균이 20일 이동평균을 최근 5거래일 안에 골든크로스", "strategy_id": "golden_cross_5_20", "params": {"fast": 5, "slow": 20}, "within_days": 5},
                          {"text": "존재하지 않는 전략", "strategy_id": "made_up", "params": {}, "within_days": 1}]},
        {"text": "영업이익이 전년 대비 증가", "source": "실적 좋은", "strategy_id": "rank_volume", "params": {"top_n": 20}, "within_days": 3},
    ],
    "unsupported": [{"text": "외국인 순매수", "reason": "수급 자료는 카탈로그에 없다"}],
    "clarifications": [{"id": "market", "question": "어느 시장을 볼까요?", "options": [{"label": "전체", "text": "KOSPI·KOSDAQ 전체"}, {"label": "KOSDAQ", "text": "KOSDAQ만"}], "selected": 7}],
    "specified": ["min_market_cap"],
}


class RefineTests(unittest.TestCase):
    def test_finalize_validates_against_catalog_and_adds_default_clarifications(self):
        result = refine.finalize(RAW, .04)
        self.assertEqual([c["strategy_id"] for c in result["conditions"]], ["sma_slope_up_20d"])
        self.assertEqual([a["strategy_id"] for a in result["conditions"][0]["alternatives"]], ["golden_cross_5_20"], "invalid alternatives are dropped")
        self.assertEqual(len(result["unsupported"]), 2, "a ranking with within_days=3 is not a valid catalog condition")
        ids = [c["id"] for c in result["clarifications"]]
        self.assertEqual(ids, ["market", "within_days"], "time axis is always asked; market cap was specified so it is not")
        self.assertEqual(result["clarifications"][0]["selected"], 1, "out-of-range selection is clamped")
        self.assertEqual(result["cost_usd"], .04)
        self.assertTrue(result["question"].startswith("다음 조건을 모두 만족하는 종목을 찾아줘.\n- 20일 이동평균이"))
        self.assertIn("- 신호는 최근 5거래일 안에 발생한 것으로 본다", result["question"])

    def test_compose_uses_chosen_alternative_and_answers(self):
        result = refine.finalize(RAW, 0)
        text = refine.compose_question(result, choices={0: 1}, answers={"within_days": 2, "market": 0})
        self.assertIn("- 5일 이동평균이 20일 이동평균을", text)
        self.assertIn("- 신호는 최근 20거래일 안에", text)
        self.assertIn("- KOSPI·KOSDAQ 전체", text)

    def test_endpoint_returns_refinement_and_maps_model_errors(self):
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        with patch.object(refine, "structured_call", return_value=(RAW, .05)):
            response = client.post("/api/analysis/refine", json={"question": "바닥찍고 올라오는 실적 좋은 종목"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["restatement"], RAW["restatement"])
        from pipeline.market_analysis.model import ModelError
        with patch.object(refine, "structured_call", side_effect=ModelError("모델이 시간 제한 안에 응답하지 않았습니다.")):
            self.assertEqual(client.post("/api/analysis/refine", json={"question": "x"}).status_code, 502)
        self.assertEqual(client.post("/api/analysis/refine", json={"question": "   "}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
