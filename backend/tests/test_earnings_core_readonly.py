"""A stale season can be calculated without modifying its saved results."""
import sqlite3
import unittest
from unittest.mock import patch

from pipeline import earnings_chain


class CoreReadOnlyTest(unittest.TestCase):
    def test_stale_recalculation_preserves_results_and_storage(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.execute('CREATE TABLE earnings_core (season TEXT, ticker TEXT, reasons TEXT, '
                     'mention_docs INTEGER, mention_sources INTEGER, computed_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        rows = {'AAA': {'market_cap': 1, 'sector': 'other', 'core_pinned': False}}
        with patch.object(earnings_chain, 'follows', return_value=rows), \
             patch.object(earnings_chain, 'mention_counts', return_value={'AAA': (0, 0)}), \
             patch.object(earnings_chain, 'holding_chain_tickers', return_value=set()):
            expected = earnings_chain.compute_core(conn, '2026Q3')
            before = list(conn.execute('SELECT * FROM earnings_core'))
            conn.execute('PRAGMA query_only=ON')
            actual = earnings_chain.core_map(conn, '2026Q3', recompute_days=-1, persist=False)
            after = list(conn.execute('SELECT * FROM earnings_core'))
        self.assertEqual(actual, expected)
        self.assertEqual([tuple(x) for x in before], [tuple(x) for x in after])
        conn.close()


if __name__ == '__main__':
    unittest.main()
