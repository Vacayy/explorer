"""실적 시즌 체인이 엔티티 병합 뒤에도 멈추지 않는다 (2026-11-06 사고: transcript_follow가 병합된 엔티티를 가리켜 11/4부터 체인 정지)."""
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from pipeline import call_reaction as cr
from pipeline import vocab


class ChainResilienceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "t.sqlite"
        c = self.connect()
        c.executescript("""
            CREATE TABLE entities(id INTEGER PRIMARY KEY, name TEXT, type TEXT);
            CREATE TABLE entity_keywords(entity_id INTEGER REFERENCES entities(id), keyword TEXT, status TEXT, UNIQUE(entity_id, keyword));
            CREATE TABLE transcript_follow(ticker TEXT PRIMARY KEY, company_name TEXT, entity_id INTEGER, active INTEGER DEFAULT 1);
            INSERT INTO entities VALUES (4196, '애플', 'company');
            INSERT INTO entity_keywords VALUES (4196, 'Apple', 'active');
            INSERT INTO transcript_follow VALUES ('AAPL', 'Apple', 4201, 1);   -- 4201은 병합으로 지워진 id
            INSERT INTO transcript_follow VALUES ('ZZZ', 'Nowhere Inc', 9999, 1);
        """)
        c.commit()
        c.close()

    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def test_repair_relinks_dangling_follow_by_name_or_clears_it(self):
        c = self.connect()
        self.assertEqual(cr.repair_follow_entities(c), 2)
        got = dict(c.execute("SELECT ticker, entity_id FROM transcript_follow").fetchall())
        self.assertEqual(got, {"AAPL": 4196, "ZZZ": None})
        c.close()

    def test_vocab_merge_rewires_undeclared_follow_reference(self):
        c = self.connect()
        cols = vocab._entity_fk_columns(c)
        self.assertIn(("transcript_follow", "entity_id"), cols)
        self.assertIn(("entity_keywords", "entity_id"), cols)
        c.close()

    def test_aliases_skip_follows_whose_entity_is_gone(self):
        with patch.object(cr, "get_connection", self.connect), \
             patch("pipeline.enrich._call_claude_code", side_effect=AssertionError("no LLM when nothing to alias")), patch("pipeline.enrich.llm_available", return_value=True):
            # AAPL은 복구 뒤 이미 별칭(Apple)이 있고, ZZZ는 엔티티가 없어 대상에서 빠진다 → 모델 호출 없음
            self.assertEqual(cr.ensure_ko_aliases(), 0)


class ConfirmByTranscriptTests(unittest.TestCase):
    def test_event_with_transcript_becomes_confirmed(self):
        from pipeline import earnings_chain as ec
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.executescript("""
            CREATE TABLE earnings_events(ticker TEXT, fiscal_year INTEGER, fiscal_period TEXT, event_date TEXT, season TEXT,
              confirmed INTEGER DEFAULT 0, updated_at TEXT, PRIMARY KEY(ticker, fiscal_year, fiscal_period));
            CREATE TABLE transcripts(id INTEGER PRIMARY KEY, ticker TEXT, fiscal_year INTEGER, fiscal_period TEXT);
            CREATE TABLE transcript_calendar(ticker TEXT, next_report_date TEXT);
        """)
        past = (date.today() - timedelta(days=2)).isoformat()
        c.execute("INSERT INTO earnings_events VALUES ('SITM', 2026, 'Q3', ?, '2026Q3', 0, NULL)", (past,))
        c.execute("INSERT INTO earnings_events VALUES ('NOPE', 2026, 'Q3', ?, '2026Q3', 0, NULL)", (past,))
        c.execute("INSERT INTO transcripts VALUES (1, 'SITM', 2026, 'Q3')")
        with patch.object(ec, "follows", return_value={"SITM": {}, "NOPE": {}}), \
             patch("pipeline.transcript._event_targets", return_value={}):
            ec.sync_events(c)
        got = dict(c.execute("SELECT ticker, confirmed FROM earnings_events").fetchall())
        self.assertEqual(got, {"SITM": 1, "NOPE": 0})


if __name__ == "__main__":
    unittest.main()
