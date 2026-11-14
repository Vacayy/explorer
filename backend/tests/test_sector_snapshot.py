"""sector_rs._snapshot 재작성 대조 (API 성능 A단계 ③-b).

옛 쿼리(GROUP BY + 조인)를 기준(oracle)으로 두고 새 종목별 시크 쿼리와 결과가 같은지 본다.
- 합성 DB: 종가 없는 행·그날 이전 행이 없는 종목·시총 없는 행.
- 실데이터 사본: PERF_DB 환경변수에 운영 DB 사본 경로를 주면 날짜 10개 이상을 대조한다(없으면 건너뜀).
  PERF_DB=/path/to/copy.db ../.venv/bin/python -m unittest tests.test_sector_snapshot
- 요청 안 메모: 같은 날짜는 한 번만 읽고, graph_activity(새 쿼리+메모) 결과는 옛 쿼리·메모 없음과 같다.
"""
import os
import sqlite3
import tempfile
import unittest
from contextlib import nullcontext
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import database
from pipeline import beneficiary, research_candidates, sector_rs


def old_snapshot(conn, on_or_before: str) -> dict[str, tuple[float, float]]:
    """재작성 전 구현 그대로(2bf68835) — 대조 기준."""
    rows = conn.execute("""
        SELECT sp.stock_code, sp.close, sp.market_cap
        FROM stock_prices sp
        JOIN (SELECT stock_code, max(trade_date) d FROM stock_prices
              WHERE trade_date <= ? AND close IS NOT NULL GROUP BY stock_code) t
          ON t.stock_code = sp.stock_code AND t.d = sp.trade_date""", (on_or_before,)).fetchall()
    return {r[0]: (r[1], r[2] or 0) for r in rows}


class SyntheticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch.object(database, "DB_PATH", Path(self.tmp.name) / "t.db").start()
        self.addCleanup(patch.stopall)
        database.init_db()
        self.conn = database.get_connection()
        self.addCleanup(self.conn.close)
        rows = [
            ("000010", "2026-01-02", 100, 1000), ("000010", "2026-01-05", 110, None), ("000010", "2026-01-06", None, 1200),
            ("000020", "2026-01-05", 50, 500), ("000020", "2026-01-07", 55, 550),
            ("000030", "2026-01-07", 9, 90),
            ("000040", "2026-01-02", None, 10),
        ]
        self.conn.executemany("INSERT INTO stock_prices (stock_code, trade_date, close, market_cap) VALUES (?,?,?,?)", rows)
        self.conn.commit()

    def test_matches_old_query(self):
        for d in ("2025-12-31", "2026-01-02", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07", "2026-12-31"):
            self.assertEqual(sector_rs._snapshot(self.conn, d), old_snapshot(self.conn, d), d)
        self.assertEqual(sector_rs._snapshot(self.conn, "2026-01-06"), {"000010": (110, 0), "000020": (50, 500)})

    def test_memo_reads_each_date_once(self):
        calls = []
        self.conn.set_trace_callback(lambda sql: calls.append(sql) if "WITH RECURSIVE codes" in sql else None)
        with sector_rs.snapshot_memo():
            a = sector_rs._snapshot(self.conn, "2026-01-06")
            b = sector_rs._snapshot(self.conn, "2026-01-06")
            sector_rs._snapshot(self.conn, "2026-01-07")
        self.assertEqual(a, b)
        self.assertEqual(len(calls), 2)
        sector_rs._snapshot(self.conn, "2026-01-06")   # 메모 밖에서는 매번 읽는다
        self.assertEqual(len(calls), 3)


PERF_DB = os.environ.get("PERF_DB")


@unittest.skipUnless(PERF_DB and Path(PERF_DB).exists(), "PERF_DB(운영 DB 사본) 없음")
class RealDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = sqlite3.connect(PERF_DB)
        cls.conn.row_factory = sqlite3.Row
        cls.latest = cls.conn.execute("SELECT max(trade_date) FROM stock_prices").fetchone()[0]

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def dates(self) -> list[str]:
        d = date.fromisoformat(self.latest)
        recent = [d - timedelta(days=k) for k in (0, 1, 7, 30, 37, 91)]          # 최신·graph_activity·sector_map이 쓰는 날
        month_ends = [date(2026, 9, 30), date(2026, 6, 30), date(2025, 12, 31), date(2026, 10, 31)]  # 10/31은 토요일
        holidays = [date(2026, 9, 25), date(2026, 10, 3), date(2026, 1, 1)]       # 추석 연휴·개천절(토)·신정
        old = [date(2023, 6, 30), date(2021, 7, 12), date(2000, 1, 3)]   # 과거 월말·시세 첫날·시세 이전(빈 결과)
        return [x.isoformat() for x in recent + month_ends + holidays + old]

    def test_matches_old_query_on_real_dates(self):
        dates = self.dates()
        self.assertGreaterEqual(len(dates), 10)
        for d in dates:
            new, old = sector_rs._snapshot(self.conn, d), old_snapshot(self.conn, d)
            self.assertEqual(new, old, d)
        print(f"\n[sector_snapshot] {len(dates)}개 날짜 일치: " + ", ".join(
            f"{d}({len(sector_rs._snapshot(self.conn, d))})" for d in dates))

    def test_graph_activity_same_as_old_snapshot_without_memo(self):
        new = beneficiary.graph_activity(self.conn)
        with patch.object(beneficiary, "snapshot_memo", nullcontext), \
                patch.object(beneficiary, "_snapshot", old_snapshot), \
                patch.object(research_candidates, "_snapshot", old_snapshot):
            old = beneficiary.graph_activity(self.conn)
        self.assertEqual(new, old)
        print(f"\n[sector_snapshot] graph_activity 노드 {len(new)}개, 수혜 종목 "
              f"{sum(len(x['beneficiaries']) for x in new)}개 일치")


if __name__ == "__main__":
    unittest.main()
