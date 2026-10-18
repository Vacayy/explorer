import unittest

from pipeline.ext_seaj import parse_backnumber


def _grid():
    # 실제 백넘버 xls(2026-09판) 축소: 제목 3행 → 머리행 3줄 → 연도는 1월 행에만, 월 칸 '8R' 수정 표시, 미래 월은 빈 행
    return [
        ["■Back Number", None, None, None, None, None, "※2024年3月25日： 23/1-12データに修正が入りました。"],
        ["半導体製造装置(日本製装置）"],
        ["Semiconductor Manufacturing Equipment(Japanese Equipment)"],
        ["年      Year", "月      Monｔｈ", "3ヶ月移動平均値/3mma", None, None, None, "BBﾚｼｵ  （BB Ratio)"],
        [None, None, "受注額(百万円）", "前年比(%)", "販売額(百万円）", "前年比(%)"],
        [None, None, "Bookings(M\\)", "Growth Rate(%)", "Billings(M\\)", "Growth Rate(%)"],
        [2005.0, 1.0, 113451.67, -0.20, 120350.33, 0.17, 0.94],
        [None, 2.0, 100782.33, -0.22, 121258.67, 0.08, 0.83],
        [None, "8R", 103110.0, 0.08, 117364.67, 0.19, 0.88],
        [None, "9(R)", None, None, 279948.0, 0.43],
        [None, "10（R）", None, None, 347054.0, 0.28],
        [2026.0, 1.0, None, None, 427507.67, 0.03, None],
        [None, 8.0, None, None, 597915, 0.474, None],
        [None, 9.0, None, None, None, None, None],
        [2027.0, 1.0],
    ]


class ParseBacknumberTests(unittest.TestCase):
    def test_billings_column_with_year_carry(self):
        rows = parse_backnumber(_grid())
        self.assertEqual(rows, [("2005-01", 120350.33), ("2005-02", 121258.67), ("2005-08", 117364.67),
                                ("2005-09", 279948.0), ("2005-10", 347054.0),
                                ("2026-01", 427507.67), ("2026-08", 597915.0)])

    def test_missing_header_raises(self):
        grid = [r for r in _grid() if not (len(r) > 4 and r[4] == "販売額(百万円）")]
        with self.assertRaises(ValueError):
            parse_backnumber(grid)

    def test_unit_change_raises(self):
        grid = _grid()
        grid[4] = [None, None, "受注額(億円）", None, "販売額(億円）"]
        with self.assertRaises(ValueError):
            parse_backnumber(grid)


if __name__ == "__main__":
    unittest.main()
