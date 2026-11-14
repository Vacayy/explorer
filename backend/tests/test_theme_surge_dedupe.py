"""주목 주제: 같은 이름이 sector·theme 두 엔티티로 갈라져 있어도 한 번만 집계한다('지정학' 중복, 2026-11-04)."""
import sqlite3
import unittest
from unittest.mock import patch

from pipeline import signals

SCHEMA = """
CREATE TABLE entities(id INTEGER PRIMARY KEY, type TEXT, name TEXT);
CREATE TABLE raw_documents(id INTEGER PRIMARY KEY, title TEXT, published_at TEXT);
CREATE TABLE entity_links(doc_id INTEGER, entity_id INTEGER, link_type TEXT);
CREATE TABLE signals(signal_type TEXT, entity_id INTEGER, date TEXT, payload_json TEXT, UNIQUE(signal_type, entity_id, date));
"""


class KeepOpen:
    """compute_theme_surge가 close()해도 메모리 DB가 사라지지 않게."""
    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def close(self):
        pass


class ThemeSurgeDedupe(unittest.TestCase):
    def test_same_name_sector_and_theme_counted_once(self):
        raw = sqlite3.connect(":memory:")
        raw.row_factory = sqlite3.Row
        self.addCleanup(raw.close)
        raw.executescript(SCHEMA)
        raw.executemany("INSERT INTO entities VALUES (?,?,?)", [(1, "sector", "지정학"), (2, "theme", "지정학"), (3, "theme", "HBM")])
        for i in range(1, 41):
            raw.execute("INSERT INTO raw_documents VALUES (?, ?, datetime('now', ?))", (i, f"d{i}", f"-{i % 3} days"))
            raw.execute("INSERT INTO entity_links VALUES (?, ?, 'topic')", (i, 1 + (i % 3)))
        raw.commit()
        with patch.object(signals, "get_connection", return_value=KeepOpen(raw)), \
             patch.object(signals, "THEME_MIN_RECENT", 1):
            out = signals.compute_theme_surge()
        names = [s["name"] for s in out]
        self.assertEqual(sorted(names), ["HBM", "지정학"])


if __name__ == "__main__":
    unittest.main()
