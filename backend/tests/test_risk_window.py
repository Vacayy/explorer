"""get_risk 창 읽기 대조 (API 성능 A단계 ④).

옛 구현(전 이력을 다 읽고 window로 자르기, 2bf68835)을 기준으로 두고, range/keys를 SQL에서 거르는 새 구현이
응답 JSON(RiskResponse 직렬화)을 바이트 단위로 똑같이 내는지 본다.
- 범위: API가 받는 전부(1m·3m·1y·3y·5y·10y·20y·all) + 없음
- 키 묶음: 프론트가 쓰는 묶음(타일 10개·위젯 4개·겹쳐 보기 단일 키) + 키 하나씩 + 전체
- 합성 DB: 짧은 이력·창 밖에서 끊긴 계열·옛 vix 행만 있는 계열·잘못된 값·미래 날짜·오래 이어지는 신호
- 실데이터 사본: PERF_DB 환경변수(없으면 건너뜀)
"""
import json
import math
import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from models.risk import RiskResponse
from pipeline import risk
from pipeline.risk import (HISTORY_START, KEYS, META, RANGES, clean_rows, delta, evaluate_signal, expected_date,
                           lag_days, window)

TILE = ['us2y', 'us10y', 'curve', 'hy', 'bbb', 'aaa', 'baa10y', 'aaa10y', 'vix', 'fear_greed']   # useRiskTiles (5y)
WIDGET = ['curve', 'vix', 'fear_greed', 'hy']                                                     # useRiskWindow (3m)
OVERLAY = ['curve', 'us10y', 'us2y', 'baa10y', 'aaa10y']                                          # useRegimeOverlay (all)
KEY_SETS = [None, TILE, WIDGET, *([k] for k in KEYS), ['us2y', 'vix'], ['bbb', 'aaa']]
SPANS = [None, *RANGES]


def old_get_risk(now: datetime) -> dict:
    """재작성 전 구현 그대로(2bf68835) — 대조 기준."""
    get_connection = risk.get_connection
    expected = expected_date(now)
    today = now.astimezone(ZoneInfo('America/New_York')).date()
    cutoff = HISTORY_START.isoformat()
    conn = get_connection()
    try:
        rows = conn.execute('SELECT snapshot_date,indicator,value,extra_json FROM market_indicators '
                            "WHERE indicator GLOB 'risk_*' AND snapshot_date>=? AND snapshot_date<=? "
                            'ORDER BY snapshot_date', (cutoff, today.isoformat())).fetchall()
        legacy = conn.execute('SELECT snapshot_date,indicator,value,extra_json FROM market_indicators '
                              "WHERE indicator IN ('vix','fear_greed') AND snapshot_date>=? AND snapshot_date<=? "
                              'ORDER BY snapshot_date', (cutoff, today.isoformat())).fetchall()
    finally:
        conn.close()
    items = {}
    for key, meta in META.items():
        selected = [r for r in rows if r['indicator'] == f'risk_{key}']
        if not selected and key in ('vix', 'fear_greed'):
            selected = [r for r in legacy if r['indicator'] == key]
        raw = clean_rows(key, [(r['snapshot_date'], r['value']) for r in selected], today)
        points = [(d, round(v * (100 if meta['unit'] == 'bp' else 1), 4)) for d, v in raw]
        sync = [r for r in rows if r['indicator'] == f'risk_sync_{key}']
        sync_meta = json.loads(sync[-1]['extra_json'] or '{}') if sync else {}
        last_meta = json.loads(selected[-1]['extra_json'] or '{}') if selected else {}
        stamp = points[-1][0] if points else None
        lag = lag_days(stamp, expected) if stamp else None
        quality = 'missing' if not points else 'stale' if lag > 2 else 'error' if sync_meta.get('error') else 'fresh'
        items[key] = {**meta, 'key': key, 'value': points[-1][1] if points else None,
                      'as_of': stamp, 'fetched_at': last_meta.get('fetched_at'),
                      'attempted_at': sync_meta.get('attempted_at'), 'error': sync_meta.get('error'),
                      'quality': quality, 'lag_days': lag, 'points': points,
                      'change_5': delta(points, 5), 'change_20': delta(points, 20)}
    two, ten = dict(items['us2y']['points']), dict(items['us10y']['points'])
    curve = [(d, round((ten[d]-two[d])*100, 4)) for d in sorted(two.keys() & ten.keys())]
    quality = 'missing' if not curve else 'stale' if lag_days(curve[-1][0], expected)>2 else 'error' if any(items[k]['quality']=='error' for k in ('us2y','us10y')) else 'fresh'
    items['curve'] = {'key': 'curve', 'label': '10Y − 2Y', 'unit': 'bp', 'source': 'FRED · DGS10 − DGS2',
                      'source_url': 'https://fred.stlouisfed.org/series/T10Y2Y',
                      'value': curve[-1][1] if curve else None, 'as_of': curve[-1][0] if curve else None,
                      'quality': quality, 'points': curve, 'change_5': delta(curve, 5),
                      'change_20': delta(curve, 20), 'fetched_at': min((items[k]['fetched_at'] for k in ('us2y','us10y') if items[k]['fetched_at']), default=None),
                      'lag_days': lag_days(curve[-1][0], expected) if curve else None,
                      'error': None, 'attempted_at': None}
    return {'items': list(items.values()), 'signal': evaluate_signal(items, expected),
            'expected_date': expected.isoformat(), 'generated_at': now.isoformat(),
            'calendar_note': '미국 연방 공휴일 + Good Friday 근사 달력 · 비정기 휴장 미반영',
            'empty': not any(item['points'] for item in items.values())}


def body(data: dict) -> bytes:
    """응답 본문 그대로(라우터 response_model 직렬화)."""
    return RiskResponse.model_validate(data).model_dump_json().encode()


class Compare:
    """라우터와 같은 경로: 파라미터가 없으면 get_risk(), 있으면 window(get_risk(span, keys), span, keys)."""
    def assert_all_equal(self, nows):
        n = 0
        for now in nows:
            full = old_get_risk(now)
            self.assertEqual(body(risk.get_risk(now)), body(full), f'{now} 전체')
            for span in SPANS:
                for keys in KEY_SETS:
                    if not (span or keys):
                        continue
                    new = window(risk.get_risk(now, span=span, keys=keys), span, keys)
                    self.assertEqual(body(new), body(window(full, span, keys)), f'{now} range={span} keys={keys}')
                    n += 1
        return n


def conn_factory(path):
    def get_connection():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    return get_connection


def bdays(start: date, end: date) -> list[str]:
    out, d = [], start
    while d <= end:
        if risk.business_day(d):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


class SyntheticTests(unittest.TestCase, Compare):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = str(Path(tmp.name) / 't.db')
        patch.object(risk, 'get_connection', conn_factory(self.path)).start()
        self.addCleanup(patch.stopall)
        c = sqlite3.connect(self.path)
        c.execute('CREATE TABLE market_indicators(snapshot_date TEXT, indicator TEXT, value REAL, extra_json TEXT, '
                  'PRIMARY KEY(snapshot_date, indicator))')
        self.c = c
        self.addCleanup(c.close)

    def put(self, ind, days, f, meta=None):
        self.c.executemany('INSERT OR REPLACE INTO market_indicators VALUES (?,?,?,?)',
                           [(d, ind, f(i), json.dumps(meta or {'fetched_at': f'{d}T22:00:00Z'})) for i, d in enumerate(days)])
        self.c.commit()

    def seed(self):
        long = bdays(date(2018, 1, 2), date(2026, 11, 5))
        self.put('risk_us2y', long[::1], lambda i: 2 + math.sin(i / 50))
        self.put('risk_us10y', [d for i, d in enumerate(long) if i % 7], lambda i: 3 + math.sin(i / 40))   # 2Y와 날짜가 어긋난다
        # hy: 3년, 마지막 300일 동안 금리 급락 + 스프레드 확대가 이어지게 → 신호 연속 판정이 창 훨씬 앞까지 거슬러 간다
        hy = bdays(date(2023, 9, 26), date(2026, 11, 3))
        self.put('risk_hy', hy, lambda i: 3 + (i - (len(hy) - 300)) * 0.05 if i > len(hy) - 300 else 3)
        self.put('risk_us10y', hy[-300:], lambda i: 5 - i * 0.03)
        self.put('risk_bbb', hy[-10:], lambda i: 1.2)                                  # 짧은 이력(21개 미만)
        self.put('risk_aaa', bdays(date(2024, 1, 2), date(2025, 6, 30)), lambda i: 0.6)  # 창 앞에서 끊긴 계열
        self.put('risk_baa10y', bdays(date(2000, 1, 3), date(2026, 11, 3)), lambda i: 1.8 if i % 13 else None)  # 빈 값 섞임
        self.put('vix', bdays(date(2026, 4, 29), date(2026, 10, 14)), lambda i: 15 + i % 9)  # 옛 vix 행만 있다
        fg = [(date(2025, 9, 29) + timedelta(days=k)).isoformat() for k in range(420)]       # 주말 포함, 미래 날짜 포함
        self.put('risk_fear_greed', fg, lambda i: 150 if i % 17 == 0 else i % 100)
        self.put('fear_greed', bdays(date(2026, 4, 29), date(2026, 10, 15)), lambda i: 40)   # risk_ 행이 있으니 쓰지 않는다
        for k in META:
            self.put(f'risk_sync_{k}', ['2026-11-04', '2026-11-05'], lambda i: None,
                     {'attempted_at': '2026-11-05T01:00:00Z', 'error': 'TimeoutError' if k == 'bbb' else None})

    def test_all_ranges_and_key_sets_match_old(self):
        self.seed()
        nows = [datetime(2026, 11, 6, 14, tzinfo=timezone.utc), datetime(2026, 7, 6, 3, tzinfo=timezone.utc),
                datetime(2025, 1, 2, 15, tzinfo=timezone.utc), datetime(2019, 3, 1, 15, tzinfo=timezone.utc)]
        n = self.assert_all_equal(nows)
        self.assertGreater(n, 300)

    def test_empty_subset_falls_back_to_all_series(self):
        self.put('risk_aaa10y', bdays(date(2026, 1, 2), date(2026, 11, 3)), lambda i: 0.8)
        n = self.assert_all_equal([datetime(2026, 11, 6, 14, tzinfo=timezone.utc)])
        self.assertGreater(n, 0)
        data = window(risk.get_risk(datetime(2026, 11, 6, 14, tzinfo=timezone.utc), span='3m', keys=['vix']), '3m', ['vix'])
        self.assertFalse(data['empty'])

    def test_empty_db(self):
        self.assert_all_equal([datetime(2026, 11, 6, 14, tzinfo=timezone.utc)])


PERF_DB = os.environ.get('PERF_DB')


@unittest.skipUnless(PERF_DB and Path(PERF_DB).exists(), 'PERF_DB(운영 DB 사본) 없음')
class RealDataTests(unittest.TestCase, Compare):
    def test_all_ranges_and_key_sets_match_old(self):
        with patch.object(risk, 'get_connection', conn_factory(PERF_DB)):
            nows = [datetime.now(timezone.utc), datetime(2026, 11, 6, 3, tzinfo=timezone.utc),
                    datetime(2026, 9, 1, 15, tzinfo=timezone.utc), datetime(2024, 12, 31, 15, tzinfo=timezone.utc)]
            n = self.assert_all_equal(nows)
        print(f'\n[risk_window] 실데이터 사본 {len(nows)}개 시점 × 범위·키 묶음 {n}가지 + 전체 응답, 바이트 일치')


if __name__ == '__main__':
    unittest.main()
