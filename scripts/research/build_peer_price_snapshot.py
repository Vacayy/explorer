"""Export a reviewed explicit regular-session research dataset. No network or DB writes.

The input keeps evidence/raw responses in the local research directory. This tool
never promotes adjustment quality or enables alerts from a session field check.
"""
import argparse
import hashlib
import json
import math
from datetime import date, datetime
from pathlib import Path


def build(source: Path, audit_path: Path, event_paths: list[Path] | None = None):
    raw = source.read_bytes()
    data = json.loads(raw)
    audit = json.loads(audit_path.read_text())
    assert audit['period']['end'] == data['asOf']
    assert audit['codes'] == len(data['series'])
    assert not audit['regular_change_price_mismatches'] and not audit['regular_change_rate_mismatches']
    issues = [dict(code=item['code'], date=item['date'], reason='전일 정규장 종가와 당일 기준가격 불일치. 원인 및 기업행사 조정 미확인.', sourceUrl=item['source']) for item in audit['base_price_mismatches']]
    if data['source']['priceField'] != 'items[].regularMarketClosingPrice':
        raise ValueError('Require explicit regular-session field')
    for event_path in event_paths or []:
        event = json.loads(event_path.read_text())
        assert event['verification'] == 'primary_original_DART_disclosure_verified'
        assert event['automatic_adjustment_applied'] is False
        issue = next(item for item in issues if item['code'] == event['code'] and item['date'] == event['effective_date'])
        issue['reason'] = event['event_name'] + '에 따른 기준가격 변경. 기업행사 조정 미반영.'
        issue['sourceUrl'] = event['landing_url']
    dates = data['dates']
    assert dates and dates == sorted(set(dates))
    assert dates[-1] == data['asOf']
    for value in dates:
        date.fromisoformat(value)
    datetime.fromisoformat(data['retrievedAt'].replace('Z', '+00:00'))
    for code, values in data['series'].items():
        assert len(code) == 6 and code.isdigit()
        assert len(values) == len(dates)
        assert all(v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0) for v in values)
    bundle_hash = hashlib.sha256(raw + audit_path.read_bytes() + b''.join(path.read_bytes() for path in event_paths or [])).hexdigest()
    return dict(version=data['asOf'] + '.' + bundle_hash[:12], asOf=data['asOf'], collectedAt=data['retrievedAt'],
                sourceUrl=data['source']['url'], sourceHash=hashlib.sha256(raw).hexdigest(),
                field='regularMarketClosingPrice', session='KRX_REGULAR', adjustmentStatus='unverified',
                dates=dates, prices=data['series'], qualityIssues=issues, caveats=data['caveats'])

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--event', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, default=Path('frontend/src/data/peer-prices.json'))
    args = parser.parse_args()
    result = build(args.input, args.audit, args.event)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(f"{len(result['prices'])} stocks x {len(result['dates'])} observations -> {args.output}")
