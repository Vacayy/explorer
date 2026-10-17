"""대만 월매출 파싱 — 민국 연월 변환, Open API 행, MOPS HTML 행(대문자 <Td>·쉼표·대상 외 제외), 3개월 YoY."""
import unittest

from pipeline.tw_revenue import _three_month_yoy, parse_mops, parse_openapi, roc_to_ym

MOPS_ROW = ("<tr align=right><td align=center>4979</td><td align=left>華星光</td><td nowrap>   327,755</td>"
            "<td nowrap>  299,362</td><td nowrap>  134,618</td><td nowrap>  9.48</td><Td nowrap>  143.47</td>"
            "<td nowrap> 2,272,478</td><td nowrap> 976,039</td><td nowrap> 132.82</td><td align=left>訂單增加</td></tr>"
            "<tr align=right><td align=center>1264</td><td align=left>德麥</td><td>1</td><td>1</td><td>1</td><td>1</td>"
            "<td>1</td><td>1</td><td>1</td><td>1</td><td>-</td></tr>")


class TwRevenueTests(unittest.TestCase):
    def test_roc(self):
        self.assertEqual(roc_to_ym("11509"), "2026-09")
        self.assertEqual(roc_to_ym("11210"), "2023-10")

    def test_mops_row(self):
        recs = parse_mops(MOPS_ROW, "2023-10", "TPEx")
        self.assertEqual(len(recs), 1)                       # 대상 밖 1264는 버린다
        r = recs[0]
        self.assertEqual((r["code"], r["revenue"], r["yoy_pct"], r["cum"]), ("4979", 327755.0, 143.47, 2272478.0))
        self.assertEqual(r["note"], "訂單增加")

    def test_openapi_row(self):
        rows = [{"資料年月": "11509", "公司代號": "2330", "公司名稱": "台積電", "營業收入-當月營收": "511857399",
                 "營業收入-去年同月增減(%)": "-", "備註": "-"}]
        r = parse_openapi(rows, "TWSE")[0]
        self.assertEqual((r["ym"], r["revenue"], r["yoy_pct"], r["note"]), ("2026-09", 511857399.0, None, None))

    def test_three_month_yoy(self):
        s = [{"revenue": 120, "last_year": 100}, {"revenue": 130, "last_year": 100}, {"revenue": 150, "last_year": 100}]
        self.assertEqual(_three_month_yoy(s), 33.3)
        self.assertIsNone(_three_month_yoy(s[:2]))


if __name__ == "__main__":
    unittest.main()
