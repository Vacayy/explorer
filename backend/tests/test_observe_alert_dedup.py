import sqlite3
import unittest
from unittest.mock import patch

from pipeline import observe
from routers.postgres_owner_legacy_fixture import _Borrowed


class ObserveAlertDedupTest(unittest.TestCase):
    def test_active_alert_is_not_sent_twice(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.execute('CREATE TABLE alert_state (key TEXT PRIMARY KEY, active INTEGER, detail TEXT, changed_at TEXT, sent_at TEXT)')
        sent = []
        with patch.object(observe, 'get_connection', return_value=_Borrowed(conn)), \
             patch.object(observe, '_conditions', return_value={'test': 'test'}):
            self.assertTrue(observe.check_alerts(send=lambda message: sent.append(message) or True)['sent'])
            self.assertFalse(observe.check_alerts(send=lambda message: sent.append(message) or True)['sent'])
        self.assertEqual(len(sent), 1)
        conn.close()


if __name__ == '__main__':
    unittest.main()
