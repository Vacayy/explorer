"""Home Risk: dated observations, independent collection, experimental joint signal.

GET is storage-only. No forward fill, no recession probability, no LLM.
Raw percentages are stored unchanged; spreads are returned in basis points.
"""
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from pandas.tseries.holiday import USFederalHolidayCalendar, GoodFriday

from database import get_connection
from pipeline.macro import _public_fred_history
from pipeline.market_regime import _fear_greed_history, _yf_history
from services import cache_service

FRED = {
    'us2y': ('DGS2', '미국 2년 국채', '%'),
    'us10y': ('DGS10', '미국 10년 국채', '%'),
    'hy': ('BAMLH0A0HYM2', 'HY OAS', 'bp'),
    'bbb': ('BAMLC0A4CBBB', 'BBB OAS', 'bp'),
    'aaa': ('BAMLC0A1CAAA', 'AAA OAS', 'bp'),
    'aaa10y': ('AAA10Y', 'Aaa − 10Y', 'bp'),
    'baa10y': ('BAA10Y', 'Baa − 10Y', 'bp'),
}
META = {k: {'label': label, 'unit': unit, 'source': f'FRED · {sid}',
            'source_url': f'https://fred.stlouisfed.org/series/{sid}'}
        for k, (sid, label, unit) in FRED.items()}
META.update({
    'vix': {'label': 'VIX', 'unit': 'pt', 'source': 'Yahoo Finance · ^VIX (Cboe)',
            'source_url': 'https://www.cboe.com/tradable-products/vix/'},
    'fear_greed': {'label': '공포·탐욕', 'unit': 'pt', 'source': 'CNN Fear & Greed · 비공식 연동',
                   'source_url': 'https://www.cnn.com/markets/fear-and-greed'},
})
HISTORY_START = date(1962, 1, 1)
LONG_HISTORY = frozenset(('us2y', 'us10y', 'aaa10y', 'baa10y'))
TTL = 6 * 60 * 60
RULE_VERSION = 'rates-credit-20obs-v1-experimental'
LOCK = threading.Lock()


@lru_cache(maxsize=128)
def holidays(year: int) -> frozenset[str]:
    start, end = f'{year}-01-01', f'{year}-12-31'
    days = list(USFederalHolidayCalendar().holidays(start=start, end=end))
    days += list(GoodFriday.dates(start, end))
    return frozenset(d.date().isoformat() for d in days)


def business_day(d: date) -> bool:
    """Conservative US federal + Good Friday approximation, not an exchange calendar."""
    return d.weekday() < 5 and d.isoformat() not in holidays(d.year)


def expected_date(now: datetime) -> date:
    # Prior US business day allows publication lag; never assume today's value exists.
    d = now.astimezone(ZoneInfo('America/New_York')).date() - timedelta(days=1)
    while not business_day(d):
        d -= timedelta(days=1)
    return d


def lag_days(observed: str, expected: date) -> int:
    d = date.fromisoformat(observed)
    count = 0
    while d < expected:
        d += timedelta(days=1)
        count += int(business_day(d))
    return count


def clean_rows(key: str, rows, today: date) -> list[tuple[str, float]]:
    values = {}
    for stamp, raw in rows:
        try:
            d, value = date.fromisoformat(stamp), float(raw)
        except (ValueError, TypeError):
            continue
        if d > today or not math.isfinite(value):
            continue
        if key == 'fear_greed' and not 0 <= value <= 100:
            continue
        if key == 'vix' and value < 0:
            continue
        values[d.isoformat()] = value
    return sorted(values.items())


def _collect(key: str):
    if key in FRED:
        if key in LONG_HISTORY:
            days = 400 if cache_service.is_cached(f'risk:history:{key}:v2') else (date.today() - HISTORY_START).days
        else:
            days = 3 * 366  # ICE OAS is limited to approximately three years by its source.
        return _public_fred_history(FRED[key][0], days=days)
    if key == 'vix':
        return _yf_history('^VIX', days=400)
    return _fear_greed_history(days=400)


def _snapshot_one(key: str) -> dict:
    cache_key = f'risk:{key}:v2'
    if cache_service.is_cached(cache_key):
        return {'key': key, 'status': 'cached', 'rows': 0}
    now = datetime.now(timezone.utc)
    attempted_at = now.isoformat()
    error = None
    try:
        rows = clean_rows(key, _collect(key), now.astimezone(ZoneInfo('America/New_York')).date())
        if not rows:
            raise ValueError('No valid observations')
    except Exception as exc:
        # Never expose request URLs (which may contain credentials) or provider bodies.
        error, rows = type(exc).__name__, []
    conn = get_connection()
    try:
        with conn:
            for stamp, value in rows:
                conn.execute('INSERT OR REPLACE INTO market_indicators '
                             '(snapshot_date,indicator,value,extra_json) VALUES (?,?,?,?)',
                             (stamp, f'risk_{key}', value, json.dumps({
                                 'source': META[key]['source'], 'fetched_at': attempted_at})))
            conn.execute('INSERT OR REPLACE INTO market_indicators '
                         '(snapshot_date,indicator,value,extra_json) VALUES (?,?,NULL,?)',
                         (now.astimezone(ZoneInfo('America/New_York')).date().isoformat(), f'risk_sync_{key}', json.dumps({
                             'attempted_at': attempted_at, 'error': error})))
    finally:
        conn.close()
    if rows:
        cache_service.set_cache(cache_key, TTL)
        if key in LONG_HISTORY:
            cache_service.set_cache(f'risk:history:{key}:v2', 365 * 86400)
    return {'key': key, 'status': 'error' if error else 'updated', 'rows': len(rows), 'error': error}


def snapshot_risk() -> dict:
    if not LOCK.acquire(blocking=False):
        return {'busy': True, 'results': []}
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(_snapshot_one, META))
        return {'busy': False, 'results': results}
    finally:
        LOCK.release()


def delta(points: list, back: int) -> float | None:
    return round(points[-1][1] - points[-back-1][1], 4) if len(points) > back else None


def evaluate_signal(items: dict, expected: date) -> dict:
    result = {'status': 'unavailable', 'label': '평가 보류', 'as_of': None,
              'rate_change_bp': None, 'credit_change_bp': None, 'consecutive': 0,
              'common_observations': 0, 'rule_version': RULE_VERSION,
              'reason': '10년 금리와 HY OAS의 유효 관측이 필요합니다.'}
    rate, credit = items['us10y'], items['hy']
    rates, spreads = dict(rate['points']), dict(credit['points'])
    common = sorted(d for d in rates.keys() & spreads.keys() if business_day(date.fromisoformat(d)))
    result['common_observations'] = len(common)
    result['as_of'] = common[-1] if common else None
    if rate['quality'] != 'fresh' or credit['quality'] != 'fresh':
        result['reason'] = '필수 지표가 미수집·지연 또는 수집 실패 상태여서 평가를 보류합니다.'
        return result
    if not common or lag_days(common[-1], expected) > 2:
        result['reason'] = '공통 관측 기준일이 지연되어 평가를 보류합니다.'
        return result
    if len(common) < 21:
        result['reason'] = '20일 변화를 계산하려면 최소 21개의 공통 관측이 필요합니다.'
        return result
    # Large gaps must not silently turn a 20-observation rule into a multi-month comparison.
    window = common[-23:]
    if any(lag_days(a, date.fromisoformat(b)) > 3 for a, b in zip(window, window[1:])):
        result['reason'] = '최근 공통 관측에 긴 공백이 있어 평가를 보류합니다.'
        return result
    def changes(i):
        d, previous = common[i], common[i-20]
        return round((rates[d]-rates[previous])*100, 4), round(spreads[d]-spreads[previous], 4)
    r, c = changes(len(common)-1)
    result.update(rate_change_bp=r, credit_change_bp=c)
    streak = 0
    for i in range(len(common)-1, 19, -1):
        rr, cc = changes(i)
        if rr <= -30 and cc >= 75:
            streak += 1
        else:
            break
    result['consecutive'] = streak
    if streak >= 3:
        status, label, reason = 'joint', '동시 경계', '금리 하락과 HY 스프레드 확대 조건이 3회 이상 연속 충족됐습니다.'
    elif streak:
        status, label, reason = 'watch', '동시 변화 관찰', '두 조건이 함께 충족됐지만 3회 지속은 아직 확인되지 않았습니다.'
    elif c >= 75:
        status, label, reason = 'credit', '신용 확대 관찰', 'HY 신용 스프레드가 확대됐습니다. 금리 급락 조건과 별개로 관찰합니다.'
    elif r <= -30:
        status, label, reason = 'rates', '금리 하락 관찰', '금리는 하락했지만 HY 스프레드 확대 조건은 동반되지 않았습니다.'
    else:
        status, label, reason = 'clear', '동시 조건 미충족', '두 경계 조건이 함께 충족되지 않았습니다. 시장의 안전을 의미하지 않습니다.'
    result.update(status=status, label=label, reason=reason)
    return result


def get_risk(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    expected = expected_date(now)
    today = now.astimezone(ZoneInfo('America/New_York')).date()
    cutoff = HISTORY_START.isoformat()
    conn = get_connection()
    try:
        rows = conn.execute('SELECT snapshot_date,indicator,value,extra_json FROM market_indicators '
                            "WHERE indicator GLOB 'risk_*' AND snapshot_date>=? AND snapshot_date<=? "
                            'ORDER BY snapshot_date', (cutoff, today.isoformat())).fetchall()
        # Reuse pre-existing sentiment observations before first explicit Risk collection.
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
