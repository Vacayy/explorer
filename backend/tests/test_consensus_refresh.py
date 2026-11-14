"""국내 목표가 컨센서스 정기 수집 — 추정 연도 교체·상태 구분 (2026-11-08, 9종목·9/10에서 멈췄던 일)."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from services import consensus_service as cs

HTML = """<html><body>
<table><tr><th>주요지표</th><th>2025/12(A)</th><th>2026/12(E)</th><th>2027/12(E)</th></tr>
<tr><td>EPS</td><td>4,000</td><td>8,000</td><td>10,000</td></tr>
<tr><td>PER</td><td>10.0</td><td>5.0</td><td>4.0</td></tr></table>
<table><tr><th>점수</th><th>투자의견</th><th>목표주가(원)</th><th>EPS(원)</th><th>PER(배)</th><th>추정기관수</th></tr>
<tr><td>4.0</td><td>250,000</td><td>8,000</td><td>5.0</td><td>21</td></tr></table>
</body></html>"""


class ConsensusRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'c.db'
        c = self.connect()
        c.execute("""CREATE TABLE consensus (id INTEGER PRIMARY KEY AUTOINCREMENT, stock_code TEXT NOT NULL,
            data_source TEXT NOT NULL DEFAULT 'fnguide', fiscal_year TEXT NOT NULL, revenue_est REAL, op_profit_est REAL,
            net_income_est REAL, eps_est REAL, bps_est REAL, per_est REAL, target_price REAL, analyst_count INTEGER,
            opinion TEXT, fetched_at TEXT DEFAULT (datetime('now')), UNIQUE(stock_code, data_source, fiscal_year))""")
        # 묵은 행: 지난 추정 연도 + 옛 목표가
        c.execute("INSERT INTO consensus (stock_code, data_source, fiscal_year, target_price, fetched_at) "
                  "VALUES ('005930', 'naver', '2025E', 506458, '2026-07-30 07:00:04')")
        c.commit(); c.close()
        for target in (patch.object(cs, 'get_connection', side_effect=self.connect),
                       patch.object(cs, 'set_cache'), patch('time.sleep')):
            target.start(); self.addCleanup(target.stop)

    def connect(self):
        c = sqlite3.connect(self.path); c.row_factory = sqlite3.Row; return c

    def rows(self):
        c = self.connect()
        r = [dict(x) for x in c.execute("SELECT fiscal_year, target_price, analyst_count, per_est FROM consensus ORDER BY fiscal_year")]
        c.close(); return r

    def test_refresh_replaces_years_and_updates_target(self):
        with patch('httpx.get', return_value=Mock(text=HTML, raise_for_status=Mock())):
            r = cs.refresh_consensus(['005930'])
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['ok'], 1)
        rows = self.rows()
        self.assertEqual([x['fiscal_year'] for x in rows], ['2026E', '2027E'])   # 지난 2025E는 지워진다
        self.assertEqual(rows[0]['target_price'], 250000)
        self.assertEqual(rows[0]['analyst_count'], 21)

    def test_request_failure_and_no_coverage_are_counted_apart(self):
        def get(url, **_):
            if '000001' in url:
                raise ConnectionError('down')
            return Mock(text='<html><table><tr><td>없음</td></tr></table></html>', raise_for_status=Mock())
        with patch('httpx.get', side_effect=get):
            r = cs.refresh_consensus(['000001', '000002'])
        self.assertEqual((r['ok'], r['no_coverage'], r['failed']), (0, 1, 1))
        self.assertEqual(r['status'], 'error')
        self.assertEqual(self.rows()[0]['fiscal_year'], '2025E')   # 실패하면 기존 행을 지우지 않는다


if __name__ == '__main__':
    unittest.main()
