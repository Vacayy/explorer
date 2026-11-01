import io
import unittest

import openpyxl

from pipeline.ext_wsts import MONTHS, parse_workbook

REGIONS = ["Americas", "Europe", "Japan", "Asia Pacific", "Worldwide"]


def _workbook(unit_note="All numbers are in 1000 US$.") -> bytes:
    # 실제 파일 레이아웃(2026-08판)을 축소: 머리말 3행 → 월 머리행 → 연도 행 + 지역 5행 반복, N열 이후 연합계·분기
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Monthly Data"
    ws.append(["36 Years WSTS Blue Book Data", None, None, None, None, "1986 to Date"])
    ws.append(["© 2025 By WSTS, Inc. All Rights Reserved."])
    ws.append([unit_note])
    ws.append([None, *MONTHS, "Total Year", "Q1", "Q2", "Q3", "Q4"])
    ws.append([2025])
    for i, reg in enumerate(REGIONS):
        ws.append([reg, *[1000 * (i + 1) + m for m in range(12)], 999999, 1, 2, 3, 4])
    ws.append([2026])  # 진행 중인 해: 9월 이후 빈칸, Q4=0 자리표시
    for i, reg in enumerate(REGIONS):
        ws.append([reg, 5000 + i, 6000 + i, *[None] * 10, 11000, 1, 0, 0, 0])
    mma = wb.create_sheet("3MMA")  # 이동평균 시트는 무시해야 한다
    mma.append([None, *MONTHS])
    mma.append([2025])
    mma.append(["Worldwide", *[1.5] * 12])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class ParseWorkbookTests(unittest.TestCase):
    def test_monthly_values_by_region(self):
        out = parse_workbook(_workbook())
        self.assertEqual(set(out), {"wsts:world", "wsts:americas", "wsts:europe", "wsts:japan", "wsts:apac"})
        world = dict(out["wsts:world"])
        self.assertEqual(world["2025-01"], 5000.0)
        self.assertEqual(world["2025-12"], 5011.0)
        self.assertEqual(world["2026-02"], 6004.0)
        self.assertNotIn("2026-03", world)  # 빈칸은 저장 대상 아님
        self.assertEqual(len(world), 14)  # 연합계·분기 열은 섞이지 않는다
        self.assertEqual(dict(out["wsts:apac"])["2025-03"], 4002.0)

    def test_unit_header_change_raises(self):
        # 단위가 바뀌면 조용히 잘못된 규모로 저장하지 않고 멈춘다
        with self.assertRaises(ValueError):
            parse_workbook(_workbook("All numbers are in Million US$."))


if __name__ == "__main__":
    unittest.main()
