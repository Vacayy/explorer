"""디스코 IR 엑셀 — 4월 시작 회계연도를 달력 분기로, 단위 머리말 확인."""
import io
import unittest

import openpyxl

from pipeline.disco_ir import _qkey, parse_workbook


def _book(unit="(Millions of Yen)"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quarterly"
    ws.append(["（単位：百万円）", unit, "FY2025", None, None, None, "FY2026"])
    ws.append(["■連結業績", "Consolidated Earnings", "1Q", "2Q", "3Q", "4Q", "1Q"])
    ws.append(["売上高", "Net Sales", 100, 110, 120, 130, 140])
    ws.append(["受注高", "Order", 90, None, 95, 99, 150])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class DiscoTests(unittest.TestCase):
    def test_fiscal_quarter_to_calendar(self):
        self.assertEqual([_qkey(2025, q) for q in (1, 2, 3, 4)], ["2025-06", "2025-09", "2025-12", "2026-03"])

    def test_parse(self):
        d = parse_workbook(_book())
        self.assertEqual(d["revenue"], {"2025-06": 100, "2025-09": 110, "2025-12": 120, "2026-03": 130, "2026-06": 140})
        self.assertNotIn("orders", d)            # 수주는 2022-03에 공시 중단 — 쓰지 않는다

    def test_unit_change_fails_loudly(self):
        with self.assertRaises(ValueError):
            parse_workbook(_book("(Thousands of Yen)"))


if __name__ == "__main__":
    unittest.main()
