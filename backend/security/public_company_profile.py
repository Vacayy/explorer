"""Reviewed company research from a prepared snapshot, never private research state."""
from contextlib import closing
import json
import re
from urllib.parse import urlsplit

from security.public_us_season import connection, _company


def stored_profile(code, *, market='us', path=None):
    reader = connection
    if market == 'kr':
        if not re.fullmatch(r'[0-9]{6}', code):
            raise LookupError('Public company unavailable')
        from security.public_kr_season import connection as reader
    elif market != 'us':
        raise LookupError('Public market unavailable')
    with closing(reader(path)) as conn:
        if market == 'us':
            company = _company(conn, code)
        else:
            row = conn.execute('SELECT stock_code FROM companies WHERE stock_code=?', (code,)).fetchone()
            if row is None:
                raise LookupError('Public company unavailable')
            company = {'ticker': row['stock_code']}
        row = conn.execute('SELECT payload_json FROM public_company_profiles WHERE ticker=?',
                           (company['ticker'],)).fetchone()
    if row is None:
        return None
    from routers.company_profile import ProfileRecord
    profile = ProfileRecord.model_validate(json.loads(row['payload_json']))
    if profile.stock_code != company['ticker']:
        raise ValueError('Prepared profile identity mismatch')
    # Public preparation must remove personal prompt and execution metadata.
    if any(value is not None for value in (profile.reason, profile.model, profile.cost_usd)):
        raise ValueError('Unreviewed research metadata')
    if profile.official_report:
        official = urlsplit(profile.official_report.url)
        if (official.scheme != 'https' or official.hostname != 'dart.fss.or.kr'
                or official.username or official.password):
            raise ValueError('Invalid official report source')
    ids = {s.id for s in profile.sources}
    if len(ids) != len(profile.sources) or profile.source_count != len(ids):
        raise ValueError('Invalid source references')
    for source in profile.sources:
        url = urlsplit(source.url)
        if (url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password
                or source.excerpt or url.hostname == 'fool.com' or url.hostname.endswith('.fool.com')
                or url.hostname == 'alphavantage.co' or url.hostname.endswith('.alphavantage.co')):
            raise ValueError('Unreviewed research source')
    for item in [*profile.business_lines, *profile.products_customers, *profile.drivers,
                 *profile.risks, *profile.recent_events]:
        if not set(item.source_ids) <= ids:
            raise ValueError('Invalid source references')
    return profile
