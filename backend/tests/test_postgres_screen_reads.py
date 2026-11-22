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


if __name__ == '__main__':
    unittest.main()
