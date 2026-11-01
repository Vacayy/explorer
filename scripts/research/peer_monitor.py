"""Validated regular-session snapshots and forward-only research observations.

No price-DB writes, signal publication, retrospective event generation or API IO.
The collector owns the writer lock; current.json is the sole publication point.
"""
import hashlib
import json
import math
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

POLICY = 'peer-observation-v1'
SOURCE = 'https://stock.naver.com/api/stockSecurity/items/v2/domestic/{code}/daily-prices/paged?size=100&index=0'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def number(row, field, positive=False):
    raw = row.get(field)
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        raise ValueError(f'invalid {field}: {raw!r}')
    value = float(raw)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f'invalid {field}: {raw!r}')
    return value


def parse_rows(payload, cutoff):
    if not isinstance(payload, dict) or not isinstance(payload.get('items'), list) or not payload['items']:
        raise ValueError('missing daily-price items')
    rows = {}
    for item in payload['items']:
        day = item['tradingDateKst']
        if date.fromisoformat(day).isoformat() != day or day in rows:
            raise ValueError('invalid/duplicate trading date')
        # A same-day live regularMarketClosingPrice is not a confirmed close.
        if day > cutoff:
            continue
        close = number(item, 'regularMarketClosingPrice', True)
        base = number(item, 'basePrice', True)
        change = number(item, 'regularMarketChangePrice')
        rate = number(item, 'regularMarketChangeRate')
        volume = number(item, 'tradingVolume')
        if volume < 0 or volume != int(volume):
            raise ValueError('invalid tradingVolume')
        if abs(close - base - change) > .001 or abs((close / base - 1) * 100 - rate) > .011:
            raise ValueError(f'{day}: regular price/change mismatch')
        rows[day] = dict(close=close, base=base, volume=volume)
    if len(rows) < 61:
        raise ValueError('fewer than 61 confirmed observations')
    return rows


def snapshot(catalog, payloads, now, known_issues):
    codes = [company['code'] for company in catalog['companies']]
    if len(codes) != len(set(codes)) or set(codes) != set(payloads):
        raise ValueError('catalog/payload membership mismatch')
    cutoff = now.date() if (now.hour, now.minute) >= (16, 30) else now.date() - timedelta(days=1)
    parsed = {code: parse_rows(payloads[code], cutoff.isoformat()) for code in codes}
    calendars = {code: sorted(rows)[-61:] for code, rows in parsed.items()}
    dates = calendars[codes[0]]
    if any(days != dates for days in calendars.values()):
        raise ValueError('inconsistent trading dates; incomplete provider refresh')
    # Never label a uniformly stale provider result as a new successful collection.
    if (now.date() - date.fromisoformat(dates[-1])).days > 7:
        raise ValueError('provider latest observation is more than 7 calendar days old')
    issues = {(i['code'], i['date']): i for i in known_issues if i['code'] in codes and dates[0] < i['date'] <= dates[-1]}
    for code, rows in parsed.items():
        ordered = sorted(rows)
        for previous, day in zip(ordered, ordered[1:]):
            if day not in dates:
                continue
            if rows[day]['base'] != rows[previous]['close']:
                issues.setdefault((code, day), dict(code=code, date=day, reason='전일 정규장 종가와 기준가격 불일치. 기업행사 조정 미확인.', sourceUrl=SOURCE.format(code=code)))
        for day in dates:
            if rows[day]['volume'] == 0:
                issues.setdefault((code, day), dict(code=code, date=day, reason='거래량 0. 거래정지 여부 미확인.', sourceUrl=SOURCE.format(code=code)))
    prices = {code: [parsed[code][day]['close'] for day in dates] for code in codes}
    quality = sorted(issues.values(), key=lambda issue: (issue['code'], issue['date']))
    content = digest(dict(dates=dates, prices=prices, qualityIssues=quality))
    return dict(version=dates[-1] + '.' + content[:12], asOf=dates[-1], collectedAt=now.isoformat(),
                sourceUrl=SOURCE, sourceHash=digest(payloads), field='regularMarketClosingPrice',
                session='KRX_REGULAR', adjustmentStatus='unverified', dates=dates, prices=prices,
                qualityIssues=quality, caveats=['기업행사 조정 미검증. 탐색용 가격변동이며 총수익이 아님.',
                  '공급자 관측일을 사용하며 공식 거래일 캘린더와 대조하지 않음.',
                  '거래량은 일별 응답 필드이며 정규장 전용 여부 미확인. 자동 신호 발행 보류.'])


def observations(catalog, prices):
    """Research metrics only: same equal-weight, leave-one-out definition as UI."""
    start = prices['dates'][-21]
    blocked = {i['code'] for i in prices['qualityIssues'] if start <= i['date'] <= prices['asOf']}
    result = []
    for group in catalog['groups']:
        members = [c['code'] for c in catalog['companies'] if group['id'] in c['groupIds']]
        if group['scope'] != 'product' or len(members) < 3:
            continue
        valid = not blocked.intersection(members)
        returns = {code: (prices['prices'][code][-1] / prices['prices'][code][-21] - 1) * 100 for code in members}
        for code in members:
            excess = returns[code] - sum(v for key, v in returns.items() if key != code) / (len(members) - 1) if valid else None
            result.append(dict(groupId=group['id'], code=code, memberCount=len(members), excess20Pp=excess,
                               condition='unavailable' if excess is None else 'strong' if excess >= 3 else 'weak' if excess <= -3 else 'neutral'))
    return result


def publish(root, catalog, prices, now):
    pointer = root / 'current.json'
    previous = json.loads(pointer.read_text()) if pointer.exists() else None
    # Hash full membership/evidence: a reused version label cannot hide an edit.
    catalog_hash = digest(catalog)
    content_key = digest(dict(catalog=catalog_hash, price=prices['version'], policy=POLICY))
    if previous and previous.get('contentKey', previous['key']) == content_key:
        return previous, 'skipped'
    if previous and prices['asOf'] < previous['prices']['asOf']:
        raise ValueError('refusing a backwards price date')
    reason = 'bootstrap'
    consecutive = False
    if previous:
        if previous['catalogHash'] != catalog_hash or previous['policy'] != POLICY:
            reason = 'catalog_or_policy_changed'
        elif prices['asOf'] == previous['prices']['asOf']:
            reason = 'same_date_revision'
        elif prices['dates'][-2] != previous['prices']['asOf']:
            reason = 'observation_gap'
        else:
            # Revised overlapping history may change 20d returns. Reset, do not backfill.
            old = previous['prices']
            shared = sorted(set(old['dates']).intersection(prices['dates']))
            revised = any(old['prices'][code][old['dates'].index(day)] != prices['prices'][code][prices['dates'].index(day)]
                          for code in prices['prices'] for day in shared)
            if revised:
                reason = 'historical_revision'
            else:
                reason = 'forward'
                consecutive = True
    baseline_on = previous['baselineOn'] if previous else now.date().isoformat()
    forward = prices['asOf'] > baseline_on and reason not in ('bootstrap', 'same_date_revision', 'catalog_or_policy_changed', 'historical_revision')
    prior = {(row['groupId'], row['code']): row for row in previous['observations']} if previous else {}
    rows = observations(catalog, prices)
    for row in rows:
        old = prior.get((row['groupId'], row['code']), {})
        eligible = forward and row['condition'] in ('strong', 'weak')
        row['observedStreak'] = (old.get('observedStreak', 0) + 1 if consecutive and old.get('condition') == row['condition'] else 1) if eligible else 0
    key = digest(dict(content=content_key, previous=previous['key'] if previous else None))
    bundle = dict(key=key, contentKey=content_key, policy=POLICY, catalogHash=catalog_hash, catalog=catalog, prices=prices,
                  baselineOn=baseline_on, publishedAt=now.isoformat(), updateReason=reason,
                  forwardObservation=forward, observations=rows, events=[],
                  signalStatus='held', signalHoldReason='기업행사 조정·공식 거래일·그룹 독립성 검증 미완료',
                  previousKey=previous['key'] if previous else None)
    # Immutable evidence is written before publishing one atomic consistent envelope.
    archive = root / 'snapshots' / (key + '.json')
    if archive.exists():
        archived = json.loads(archive.read_text())
        if archived['previousKey'] != bundle['previousKey']:
            raise ValueError('snapshot already archived; refusing to rewrite observation history')
        bundle = archived  # Recover a crash after archive write, before pointer replace.
    else:
        atomic_json(archive, bundle)
    atomic_json(pointer, bundle)
    return bundle, 'ok'
