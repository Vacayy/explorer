import io
import unittest

import openpyxl

from pipeline.ext_census_dc import parse_c30


def _workbook(dc_header="Data center") -> bytes:
    # 실제 privtime/privsatime 레이아웃 축소: 제목 2행 + 빈 행 → 4행 머리말, 최신월이 위, p/r 접미사, 2014 이전 빈칸, 하단 각주
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Value of Private Construction Put in Place - Not Seasonally Adjusted"])
    ws.append(["(Millions of dollars. ...)"])
    ws.append([])
    ws.append(["Date", "Total\nPrivate Construction1", "Office", "General", dc_header, "Financial"])
    ws.append(["Aug-26p", 149209, 11886, 4058, 7535, 252])
    ws.append(["Jul-26r", 146206, 11124, 3936, 6898, 248])
    ws.append(["Jan-14", 70000, 3000, 2000, 1200, 300])
    ws.append(["Dec-13", 69000, 2900, None, "", None])
    ws.append(["Jan-93", 30000, 1000, None, None, None])
    ws.append([])
    ws.append(["p Preliminary r Revised"])
    ws.append(["Source: U.S. Census Bureau, Construction Spending, October 1, 2026."])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class ParseC30Tests(unittest.TestCase):
    def test_data_center_column(self):
        rows = parse_c30(_workbook())
        self.assertEqual(rows, [("2014-01", 1200.0), ("2026-07", 6898.0), ("2026-08", 7535.0)])

    def test_missing_column_raises(self):
        with self.assertRaises(ValueError):
            parse_c30(_workbook("Data centre"))


if __name__ == "__main__":
    unittest.main()
