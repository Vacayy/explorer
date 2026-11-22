import unittest

from pipeline import postgres_us_briefing as briefing


class FakePG:
    """Answers the loader's statements from rows per legacy table; records which tables were read."""

    def __init__(self, rows):
        self.rows, self.read = rows, []

    def execute(self, sql, args=()):
        if 'FROM legacy_snapshot_tables' in sql:
            found = [(t, f'CREATE TABLE {t} (id INTEGER, trade_date TEXT, ticker TEXT, synthesis_json TEXT)')
                     for t in args[0]]
        elif 'pg_depend' in sql:
            found = [('base_schema',)]
        elif 'current_schema()' in sql:
            found = [('here_schema',)]
        elif 'FROM legacy_snapshot_rows' in sql:
            table = args[0] if args else 'market_indicators'
            self.read.append(table)
            found = [(row,) for row in self.rows.get(table, [])]
        else:
            found = []
        return type('Result', (), {'fetchall': lambda s: found, 'fetchone': lambda s: found[0] if found else None,
                                   '__iter__': lambda s: iter(found)})()


class UsBriefingReadTest(unittest.TestCase):
    def test_a_past_day_without_its_movers_reads_only_the_stored_synthesis(self):
        pg = FakePG({'us_movers': [{'trade_date': '2026-11-20', 'ticker': 'NVDA'}],
                     'us_briefings': [{'trade_date': '2026-11-17', 'synthesis_json': '{}'}]})
        mem = briefing.load(pg, trade_date='2026-11-17')
        self.assertEqual(pg.read, ['us_movers', 'us_briefings'])
        self.assertEqual(mem.execute('SELECT trade_date FROM us_briefings').fetchone()[0], '2026-11-17')

    def test_read_indexes_are_partial_expression_indexes_built_without_blocking_writes(self):
        found = briefing.read_indexes(FakePG({}))
        self.assertEqual([schema for schema, _, _ in found], ['base_schema'] * 3 + ['here_schema'])
        for _schema, name, ddl in found:
            self.assertIn('CREATE INDEX CONCURRENTLY IF NOT EXISTS ' + name, ddl)
            self.assertIn("WHERE table_name='", ddl)


if __name__ == '__main__':
    unittest.main()
