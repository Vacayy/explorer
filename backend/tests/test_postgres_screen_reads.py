import unittest

from pipeline import postgres_screen_reads as screens


class ScreenReadsTest(unittest.TestCase):
    def test_series_lists_are_the_legacy_reads_own(self):
        self.assertIn('index_kospi', screens._index_series())
        self.assertIn('risk_us10y', screens._macro_series())
        self.assertTrue({'risk_vix', 'vkospi', 'kospi_vol'} <= set(screens._regime_series()))

    def test_every_screen_names_its_tables_and_load(self):
        for name, (tables, load) in screens.SCREENS.items():
            self.assertTrue(tables and callable(load), name)

    def test_breadth_uses_the_newest_two_full_days(self):
        answers = iter([('2026-11-20',), [('2026-11-20', 2700), ('2026-11-19', 1000), ('2026-11-18', 2733)],
                        (5, 3, 1)])

        class PG:
            def execute(self, sql, args=()):
                value = next(answers)
                return type('R', (), {'fetchone': lambda s: value, 'fetchall': lambda s: value})()
        self.assertEqual(screens.kr_breadth(PG()), {'trade_date': '2026-11-20', 'prev_date': '2026-11-18', 'up': 5,
                                                     'down': 3, 'flat': 1, 'up_ratio': 0.625})


if __name__ == '__main__':
    unittest.main()
