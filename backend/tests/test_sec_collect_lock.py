"""SEC 8-K 수집은 네트워크를 기다리는 동안 쓰기 트랜잭션을 쥐지 않는다.

2026-10-15·16 07:20 call_momentum의 cm_sec가 회사마다 UPDATE 뒤 SEC 호출을 하며 쓰기 잠금을 쥐었다.
그 사이 07:24 30분 체인 전 단계와 자기 job_runs 기록이 'database is locked'로 죽었다.
"""
import sqlite3
import unittest
from unittest.mock import patch

from pipeline import sec_filings as sec


class SecCollectLockTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript("""
            CREATE TABLE transcript_follow(ticker TEXT, fiscal_year_end TEXT, sic TEXT);
            CREATE TABLE earnings_releases(ticker TEXT, accession TEXT);
            CREATE TABLE stored(ticker TEXT);
            INSERT INTO transcript_follow(ticker) VALUES ('AAA'), ('BBB');
        """)
        self.conn.commit()
        self.follows = [{"ticker": "AAA"}, {"ticker": "BBB"}]
        self.locked_waits = 0

    def network(self, *_a, **_k):
        # collect가 회사별 예외를 삼키므로 assert 대신 기록해 두고 끝에서 본다
        self.locked_waits += self.conn.in_transaction

    def filings(self, cik, since, meta):
        self.network()
        meta["fiscal_year_end"] = "1231"
        return [{"accession": f"acc-{cik}"}]

    def exhibits(self, cik, accession):
        self.network()
        if cik == 2:
            raise ConnectionError("sec down")
        return [{"url": f"u-{cik}"}]

    def get(self, url):
        self.network()
        return "x" * 600

    def store(self, conn, f, filing, ex, text, entity_id):
        conn.execute("INSERT INTO stored VALUES (?)", (f["ticker"],))
        return True

    def test_no_write_transaction_during_network_or_after_a_failed_company(self):
        with patch.object(sec, "cik_map", return_value={"AAA": 1, "BBB": 2}), \
             patch.object(sec, "earnings_filings", side_effect=self.filings), \
             patch.object(sec, "exhibits", side_effect=self.exhibits), \
             patch.object(sec, "_get", side_effect=self.get), \
             patch.object(sec, "to_text", side_effect=lambda t: t), \
             patch.object(sec, "_store", side_effect=self.store):
            stats = sec.collect(self.conn, self.follows)
        self.assertEqual(self.locked_waits, 0, "네트워크 대기 중 쓰기 트랜잭션이 열려 있었다")
        self.assertEqual(stats["stored"], 1)
        self.assertEqual(len(stats["errors"]), 1)
        self.assertFalse(self.conn.in_transaction, "마지막 회사 실패 뒤 트랜잭션이 열린 채 남았다")
        fye = dict(self.conn.execute("SELECT ticker, fiscal_year_end FROM transcript_follow"))
        self.assertEqual(fye["AAA"], "1231")


if __name__ == "__main__":
    unittest.main()
