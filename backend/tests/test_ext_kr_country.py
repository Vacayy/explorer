"""한국 수출 국가별 — 월 행만 합산, 총계 행·제외 HS는 버림, 오류 응답은 예외."""
import unittest

from pipeline.ext_kr_country import _windows, parse

XML = ("<response><header><resultCode>00</resultCode><resultMsg>정상서비스.</resultMsg></header><body><items>"
       "<item><expDlr>733798502</expDlr><hsCd>-</hsCd><year>총계</year></item>"
       "<item><expDlr>6293588</expDlr><hsCd>848610</hsCd><year>2026.07</year></item>"
       "<item><expDlr>76771056</expDlr><hsCd>848620</hsCd><year>2026.07</year></item>"
       "<item><expDlr>46548806</expDlr><hsCd>848630</hsCd><year>2026.07</year></item>"
       "<item><expDlr>150023543</expDlr><hsCd>848620</hsCd><year>2026.08</year></item>"
       "</items></body></response>")


class KrCountryTests(unittest.TestCase):
    def test_sums_months_and_excludes(self):
        self.assertEqual(parse(XML, {"848630"}), {"2026-07": 6293588 + 76771056, "2026-08": 150023543})

    def test_error_response_raises(self):
        bad = ("<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</errMsg>"
               "<returnAuthMsg>등록되지 않은 서비스키</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>")
        with self.assertRaises(RuntimeError):
            parse(bad, set())

    def test_windows_split_by_year(self):
        self.assertEqual(_windows("201911", "202102"), [("201911", "201912"), ("202001", "202012"), ("202101", "202102")])


if __name__ == "__main__":
    unittest.main()
