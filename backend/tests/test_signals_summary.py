"""신호 요약 GET — 유형별 최신일 건수·상위 3 (탐색 › 신호 인덱스, '오늘의 신호' 위젯). 읽기 전용."""
import json
import sqlite3
import unittest
from unittest import mock

from routers import spine_signals as ss


def _db():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT, aliases TEXT);
        CREATE TABLE signals (id INTEGER PRIMARY KEY, signal_type TEXT, entity_id INT, date TEXT, payload_json TEXT,
                              interpretation TEXT, interpretation_model TEXT);
        INSERT INTO entities VALUES (1,'삼성전자','005930'),(2,'SK하이닉스','000660'),(3,'NAVER','035420'),(4,'Adobe',NULL);
    """)
    rows = [
        ("mention_surge", 1, "2026-10-16", {"count_7d": 10}),
        ("mention_surge", 2, "2026-10-16", {"count_7d": 99}),
        ("mention_surge", 3, "2026-10-16", {"count_7d": 30}),
        ("mention_surge", 1, "2026-10-15", {"count_7d": 500}),   # 최신일 아님 → 상위에 안 든다
        ("volume_spike", 3, "2026-10-15", {"ratio": 4.0}),
        ("call_momentum", 4, "2026-09-10", {"ticker": "ADBE", "score": 16.0}),
    ]
    for t, e, d, p in rows:
        c.execute("INSERT INTO signals (signal_type, entity_id, date, payload_json) VALUES (?,?,?,?)", (t, e, d, json.dumps(p)))
    return c


class _Conn:
    def __init__(self, c): self.c = c
    def execute(self, *a): return self.c.execute(*a)
    def close(self): pass


class SummaryTests(unittest.TestCase):
    def test_counts_latest_date_per_type_and_ranks_top(self):
        c = _db()
        with mock.patch.object(ss, "get_connection", lambda: _Conn(c)):
            out = ss.signals_summary(days=90).model_dump()
        by = {t["type"]: t for t in out["types"]}
        self.assertEqual(out["as_of"], "2026-10-16")            # 원천 시각 = 신호 최신일
        ms = by["mention_surge"]
        self.assertEqual((ms["latest_date"], ms["count_latest"], ms["count_window"]), ("2026-10-16", 3, 4))
        self.assertEqual([x["name"] for x in ms["top"]], ["SK하이닉스", "NAVER", "삼성전자"])
        self.assertEqual(by["volume_spike"]["latest_date"], "2026-10-15")
        self.assertEqual(by["call_momentum"]["top"][0]["ticker"], "ADBE")

    def test_empty(self):
        c = _db()
        c.execute("DELETE FROM signals")
        with mock.patch.object(ss, "get_connection", lambda: _Conn(c)):
            out = ss.signals_summary(days=7).model_dump()
        self.assertEqual(out, {"as_of": None, "types": []})


if __name__ == "__main__":
    unittest.main()
