import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import refactor_collect_job as job
import refactor_collect_trial as trial


class FakePG:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, query, params):
        return [(row,) for row in self.rows.get(params[0], [])]


class USFundPublishGuardTest(unittest.TestCase):
    def test_existing_keys_must_survive_even_if_table_grows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'work.sqlite'
            with sqlite3.connect(path) as work:
                work.execute('CREATE TABLE us_segments (ticker TEXT, q TEXT, segment_name TEXT, revenue REAL, PRIMARY KEY(ticker,q,segment_name))')
                work.executemany('INSERT INTO us_segments VALUES (?,?,?,?)', [('A', '1', 'new', 1), ('A', '1', 'other', 2)])
            pg = FakePG({'us_segments': [{'ticker': 'A', 'q': '1', 'segment_name': 'old'}]})
            with self.assertRaises(trial.HeldBack):
                job.validate_usfund_keys(pg, path, {'us_segments'})
            with sqlite3.connect(path) as work:
                work.execute('INSERT INTO us_segments VALUES (?,?,?,?)', ('A', '1', 'old', 3))
            job.validate_usfund_keys(pg, path, {'us_segments'})
