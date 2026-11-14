"""분기 손익 흐름 — Sankey 노드·링크·콜아웃 규칙 (ia-redesign §4.13).

픽스처 두 개로 검증:
- SK하이닉스 2026 Q2 (KR, 연결, CIS 줄 그대로): 매출 79.3조, 영업이익 60.5조(OPM 76.3%), 순이익 93.9조.
  영업외수익이 커 콜아웃 Rule 1(순이익 > 매출) 트리거.
- NVIDIA FY27 Q2 (US, GAAP, 10-Q): 매출 $96.22B, 영업이익 $63.73B(OPM 66.2%), 순이익 $59.69B.
  영업외수익은 전 분기 $16.4B → 이번 $7.77B로 감소 → 콜아웃 Rule 2(NI QoQ ≠ OP QoQ) 트리거.

핵심 체크:
1. 노드 들어온 합 = 나간 합(반올림 1% 이내) — 원천 손익 수지 유지
2. 음수 흐름 없음(FlowLink.value > 0)
3. 라벨 규칙 — margin·YoY·QoQ·이익률(%p)
4. 콜아웃 Rule 번호
"""
import unittest

from pipeline.income_flow import build_kr_income_flow, build_us_income_flow


def _balance(result):
    """노드별 들어온 합 / 나간 합. 반올림 1% 이내면 OK — Sankey가 그릴 수 있다는 뜻."""
    in_sum = {}
    out_sum = {}
    for l in result.links:
        in_sum[l.target] = in_sum.get(l.target, 0.0) + l.value
        out_sum[l.source] = out_sum.get(l.source, 0.0) + l.value
    return in_sum, out_sum


def _by_id(result):
    return {n.id: n for n in result.nodes}


# ── SK하이닉스 2026 Q2 픽스처 (DART 저장 그대로, CFS·CIS) ─────────────────────
#
# 여기서는 _build_financial_response가 돌려주는 FinancialResponse 형태를 모사한다.
# 실 DB 조회는 다른 테스트에서 — 이 테스트는 순수 함수 build_kr_income_flow를 검증.
SKHYNIX_RESPONSE = {
    "periods": ["24.06", "25.03", "25.06", "26.03", "26.06"],
    "rows": [
        # idx   24.06        25.03        25.06        26.03        26.06
        {"account_nm": "매출액",          "values": [str(int(16.4e12)), str(int(17.6e12)), str(int(22.2e12)), str(int(52.6e12)), str(int(79.3e12))]},
        {"account_nm": "매출원가",        "values": [str(int(13.5e12)), str(int(11.2e12)), str(int(12.9e12)), str(int(10.9e12)), str(int(13.3e12))]},
        {"account_nm": "매출총이익",      "values": [str(int(2.9e12)),  str(int(6.4e12)),  str(int(9.3e12)),  str(int(41.7e12)), str(int(66.0e12))]},
        {"account_nm": "판매비와관리비",  "values": [str(int(0.8e12)),  str(int(1.3e12)),  str(int(2.0e12)),  str(int(4.1e12)),  str(int(5.5e12))]},
        {"account_nm": "영업이익",        "values": [str(int(2.1e12)),  str(int(5.1e12)),  str(int(7.3e12)),  str(int(37.6e12)), str(int(60.5e12))]},
        {"account_nm": "금융수익",        "values": [str(int(0.8e12)),  str(int(0.5e12)),  str(int(0.6e12)),  str(int(17.1e12)), str(int(65.9e12))]},
        {"account_nm": "금융비용",        "values": [str(int(1.5e12)),  str(int(1.2e12)),  str(int(0.9e12)),  str(int(3.0e12)),  str(int(3.6e12))]},
        {"account_nm": "기타영업외수익",  "values": [str(int(0.05e12)), str(int(0.02e12)), str(int(0.03e12)), str(int(0.015e12)), str(int(0.014e12))]},
        {"account_nm": "기타영업외비용",  "values": [str(int(0.05e12)), str(int(0.02e12)), str(int(0.03e12)), str(int(0.015e12)), str(int(0.046e12))]},
        {"account_nm": "법인세비용차감전순이익", "values": [str(int(1.4e12)), str(int(4.5e12)), str(int(7.1e12)), str(int(51.6e12)), str(int(122.7e12))]},
        {"account_nm": "법인세비용",      "values": [str(int(0.4e12)),  str(int(1.3e12)),  str(int(2.0e12)),  str(int(11.3e12)), str(int(28.8e12))]},
        {"account_nm": "당기순이익",      "values": [str(int(1.0e12)),  str(int(3.2e12)),  str(int(5.1e12)),  str(int(40.3e12)), str(int(93.9e12))]},
    ],
}


# ── NVIDIA FY27 Q2 (us_quarterly 라벨 '2026-09') ──────────────────────────────
# 분기 키는 '달력 분기 끝월 YYYY-MM'. 전 분기는 -3개월, 전년 동기는 -12개월. 테스트가 YoY·QoQ·콜아웃 Rule 2를
# 돌릴 수 있도록 2025-09·2026-06을 모두 채웠다.
NVIDIA_LOOKUP = {
    "revenue":     {"2025-09": 46743e6, "2026-06": 81615e6, "2026-09": 96221e6},
    "cogs":        {"2025-09": 11891e6, "2026-06": 20428e6, "2026-09": 24079e6},
    "rnd":         {"2025-09": 4378e6,  "2026-06": 6228e6,  "2026-09": 7054e6},
    "sga":         {"2025-09": 897e6,   "2026-06": 1202e6,  "2026-09": 1354e6},
    "op_income":   {"2025-09": 28445e6, "2026-06": 53757e6, "2026-09": 63734e6},
    "pretax":      {"2025-09": 30594e6, "2026-06": 70124e6, "2026-09": 71507e6},
    "tax":         {"2025-09": 4195e6,  "2026-06": 11782e6, "2026-09": 11819e6},
    "net_income":  {"2025-09": 26399e6, "2026-06": 58342e6, "2026-09": 59688e6},
}


class SkHynixIncomeFlowTests(unittest.TestCase):
    """SK하이닉스 2026 Q2 — 반기보고서(=Q2 단일분기) 기준 Sankey."""

    def setUp(self):
        self.result = build_kr_income_flow(SKHYNIX_RESPONSE, "26.06",
                                            stage="quarterly_report", as_of="2026-07-29", fs_div="CFS")
        self.assertIsNotNone(self.result)

    def test_key_values(self):
        n = _by_id(self.result)
        self.assertAlmostEqual(n["revenue"].value, 79.3e12, delta=0.1e12)
        self.assertAlmostEqual(n["op_income"].value, 60.5e12, delta=0.1e12)
        self.assertAlmostEqual(n["net_income"].value, 93.9e12, delta=0.1e12)

    def test_node_balance(self):
        in_sum, out_sum = _balance(self.result)
        for n in self.result.nodes:
            incoming = in_sum.get(n.id, 0.0)
            outgoing = out_sum.get(n.id, 0.0)
            if n.kind in ("revenue", "inflow"):
                # 소스 — 나가는 합 = 노드값
                self.assertAlmostEqual(outgoing, n.value, delta=n.value * 0.01,
                                        msg=f"{n.id} source out={outgoing} val={n.value}")
            elif outgoing == 0:
                # 끝(sink) — 들어오는 합 = 노드값
                self.assertAlmostEqual(incoming, n.value, delta=n.value * 0.01,
                                        msg=f"{n.id} sink in={incoming} val={n.value}")
            else:
                # 중간 — 들어온 합 = 나간 합
                self.assertAlmostEqual(incoming, outgoing, delta=max(incoming, outgoing) * 0.01,
                                        msg=f"{n.id} in={incoming} out={outgoing}")

    def test_no_negative_links(self):
        for l in self.result.links:
            self.assertGreater(l.value, 0, msg=f"{l.source}→{l.target} must be positive")

    def test_margin_labels(self):
        n = _by_id(self.result)
        self.assertAlmostEqual(n["op_income"].subs.margin, 76.3, delta=0.5)
        self.assertAlmostEqual(n["net_income"].subs.margin, 118.4, delta=0.5)
        # YoY/QoQ 존재
        self.assertIsNotNone(n["revenue"].subs.yoy)
        self.assertIsNotNone(n["revenue"].subs.qoq)

    def test_callout_rule_1(self):
        # 순이익(93.9조) > 매출(79.3조) → Rule 1
        self.assertIsNotNone(self.result.callout)
        self.assertEqual(self.result.callout.rule, 1)


class NvidiaIncomeFlowTests(unittest.TestCase):
    """NVIDIA FY27 Q2 (달력 2026-09) — SEC XBRL 분기 손익."""

    def setUp(self):
        self.result = build_us_income_flow(NVIDIA_LOOKUP, "2026-09")
        self.assertIsNotNone(self.result)

    def test_key_values(self):
        n = _by_id(self.result)
        self.assertAlmostEqual(n["revenue"].value, 96221e6, delta=5e6)
        self.assertAlmostEqual(n["op_income"].value, 63734e6, delta=5e6)
        self.assertAlmostEqual(n["net_income"].value, 59688e6, delta=5e6)
        self.assertAlmostEqual(n["opex_rnd"].value, 7054e6, delta=5e6)
        self.assertAlmostEqual(n["opex_sga"].value, 1354e6, delta=5e6)

    def test_node_balance(self):
        in_sum, out_sum = _balance(self.result)
        for n in self.result.nodes:
            incoming = in_sum.get(n.id, 0.0)
            outgoing = out_sum.get(n.id, 0.0)
            if n.kind in ("revenue", "inflow"):
                self.assertAlmostEqual(outgoing, n.value, delta=n.value * 0.01,
                                        msg=f"{n.id} source out={outgoing} val={n.value}")
            elif outgoing == 0:
                self.assertAlmostEqual(incoming, n.value, delta=n.value * 0.01,
                                        msg=f"{n.id} sink in={incoming} val={n.value}")
            else:
                self.assertAlmostEqual(incoming, outgoing, delta=max(incoming, outgoing) * 0.01,
                                        msg=f"{n.id} in={incoming} out={outgoing}")

    def test_margin_labels(self):
        n = _by_id(self.result)
        self.assertAlmostEqual(n["gross_profit"].subs.margin, 75.0, delta=0.2)
        self.assertAlmostEqual(n["op_income"].subs.margin, 66.2, delta=0.3)
        self.assertAlmostEqual(n["net_income"].subs.margin, 62.0, delta=0.3)

    def test_callout_rule_2(self):
        # Op QoQ +19% vs NI QoQ +2.3% → Rule 2
        self.assertIsNotNone(self.result.callout)
        self.assertEqual(self.result.callout.rule, 2)

    def test_empty_segments(self):
        # §6: 세그먼트 자동 수집 없음 → 빈 리스트
        self.assertEqual(self.result.segments, [])


if __name__ == "__main__":
    unittest.main()
