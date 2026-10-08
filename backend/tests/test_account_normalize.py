import unittest

from services.dart_service import _normalize_account_name


class AccountNormalizeTests(unittest.TestCase):
    def test_operating_profit_variants(self):
        # 원익IPS는 영업이익을 '영업순손익'으로 공시한다 — 매핑이 없으면 요약·KPI에서 영업이익이 전부 빈칸
        for name in ("영업이익", "영업이익(손실)", "영업손익", "영업순손익"):
            self.assertEqual(_normalize_account_name(name), "영업이익")

    def test_revenue_variants(self):
        # 원익IPS 26.06은 손익계산서 최상단을 '수익'으로만 적었다
        for name in ("매출액", "수익(매출액)", "영업수익", "수익"):
            self.assertEqual(_normalize_account_name(name), "매출액")


if __name__ == "__main__":
    unittest.main()
