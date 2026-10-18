import unittest

from pipeline.ext_tw_orders import FILES, parse_csv

# 실제 파일 레이아웃(2026-10 확인)을 축소: BOM + 머리행, 資料期는 민국 연월 YYYMM
TOTAL = ("﻿統計項目,資料期(民國年),統計值(美元),計量單位(美元),統計值(新台幣),計量單位(新台幣)\r\n"
         "外銷訂單金額,07301,2627,百萬美元,1056,新臺幣億元\r\n"
         "外銷訂單金額,11506,95262,百萬美元,30120,新臺幣億元\r\n"
         "外銷訂單金額,11507,97939,百萬美元,31543,新臺幣億元\r\n")
ICT = ("﻿統計項目,貨品別,資料期(民國年),統計值(金額),計量單位\r\n"
       "外銷訂單金額_美元,資訊與通信產品,07301,92,百萬美元\r\n"
       "外銷訂單金額_美元,資訊與通信產品,11507,33269,百萬美元\r\n")


class ParseCsvTests(unittest.TestCase):
    def test_total_roc_period_and_usd_column(self):
        _, value_col, unit_col = FILES["tw_orders:total"]
        rows = parse_csv(TOTAL, value_col, unit_col)
        self.assertEqual(rows, [("1984-01", 2627.0), ("2026-06", 95262.0), ("2026-07", 97939.0)])

    def test_category_file(self):
        _, value_col, unit_col = FILES["tw_orders:ict"]
        self.assertEqual(parse_csv(ICT, value_col, unit_col), [("1984-01", 92.0), ("2026-07", 33269.0)])

    def test_blank_value_skipped(self):
        _, value_col, unit_col = FILES["tw_orders:ict"]
        text = ICT + "外銷訂單金額_美元,資訊與通信產品,11508,-,百萬美元\r\n"
        self.assertEqual(len(parse_csv(text, value_col, unit_col)), 2)

    def test_unit_change_raises(self):
        _, value_col, unit_col = FILES["tw_orders:ict"]
        with self.assertRaises(ValueError):
            parse_csv(ICT.replace("百萬美元", "億美元"), value_col, unit_col)

    def test_missing_column_raises(self):
        with self.assertRaises(ValueError):
            parse_csv(ICT.replace("統計值(金額)", "金額"), "統計值(金額)", "計量單位")


if __name__ == "__main__":
    unittest.main()
