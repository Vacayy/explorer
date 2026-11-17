import unittest
from unittest.mock import patch

from pipeline import observe


class WeeklyCostTest(unittest.TestCase):
    def test_unknown_job_cost_is_not_reported_as_zero(self):
        summary = {
            'jobs': {'total': {'ok': 0, 'runs': 0, 'err': 0, 'partial': 0}, 'streaks': [], 'failing': [], 'chronic': []},
            'costs': {'usd': 0, 'change_pct': None, 'by_job': [{'name': '작업', 'usd': None, 'share': 0}]},
            'usage': {'visits': 0}, 'value': {'expectation_grades': {}, 'rates': []},
            'api': {'requests': 0}, 'client_errors': [],
        }
        with patch.object(observe, 'summary', return_value=summary):
            message = observe.weekly_message()
        self.assertIn('작업 비용 미집계', message)
        self.assertNotIn('작업 $0.0', message)


if __name__ == '__main__':
    unittest.main()
