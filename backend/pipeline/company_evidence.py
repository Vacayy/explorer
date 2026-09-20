"""Stored company evidence only: no generation, network requests or fetched-at substitution."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit


def publication(value, zone):
    """Legacy naive timestamps in the spine are UTC; date-only publications have no clock."""
    value = (value or '').strip()
    if len(value) == 8 and value.isdigit():
        value = f'{value[:4]}-{value[4:6]}-{value[6:]}'
    try:
        if len(value) == 10:
            return datetime.combine(date.fromisoformat(value), time(), zone), False
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed, True
    except (ValueError, TypeError):
        return None, False


def company_evidence(conn, company, *, start=None, end=None, cutoff='end', after=False,
                     source='', q='', page=1, size=20, market='kr', now=None):
    zone = ZoneInfo('Asia/Seoul' if market == 'kr' else 'America/New_York')
    now = now or datetime.now(timezone.utc)
    start_day = date.fromisoformat(start) if start else None
    end_day = date.fromisoformat(end) if end else None
    if start_day and end_day and start_day > end_day:
        raise ValueError('시작일은 종료일보다 늦을 수 없습니다.')
    closing = time(15, 30) if market == 'kr' else time(16)
    boundary = (datetime.combine(end_day, closing, zone) if cutoff == 'close' else
                datetime.combine(end_day + timedelta(days=1), time(), zone)) if end_day else None
    # An indexed ID candidate set avoids scanning every document; IN also deduplicates links.
    rows = conn.execute('''
        SELECT rd.id, rd.source_type, rd.source_id, rd.title, rd.url, rd.published_at,
               substr(rd.markdown,1,600) excerpt,
               instr(lower(COALESCE(rd.title,'') || ' ' || COALESCE(rd.markdown,'')),lower(?)) matched
        FROM raw_documents rd WHERE rd.id IN (
            SELECT el.doc_id FROM entity_links el JOIN entities e ON e.id=el.entity_id
            WHERE el.link_type='stock' AND e.status IS NOT 'merged'
            AND (e.aliases=? OR (e.aliases IS NULL AND e.name=?)))
    ''', (q.strip(), company, company)).fetchall()
    candidates = [dict(r, id=f'doc:{r["id"]}', doc_id=r['id'], relation='기업 연결 자료') for r in rows]
    # Direct disclosures are a separate store, available even before entity enrichment.
    disclosures = conn.execute('''
        SELECT d.* FROM disclosures d JOIN companies c ON c.corp_code=d.corp_code
        WHERE c.stock_code=?
    ''', (company,)).fetchall()
    for r in disclosures:
        candidates.append(dict(id=f'disclosure:{r["rcp_no"]}', doc_id=None, source_type='disclosure',
                               source_id=r['flr_nm'] or 'DART', title=r['report_nm'],
                               url=r['dart_url'] or f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r["rcp_no"]}',
                               published_at=r['rcept_dt'], excerpt='', relation='기업 직접 공시',
                               matched=q.strip().lower() in (r['report_nm'] or '').lower()))
    available, result, unknown, uncertain = {}, [], 0, 0
    for row in candidates:
        stamp, precise = publication(row['published_at'], zone)
        if stamp is None:
            unknown += 1
            continue
        day = stamp.astimezone(zone).date()
        if stamp > now:
            continue
        coverage = available.setdefault(row['source_type'], {'source': row['source_type'], 'first': str(day), 'last': str(day), 'count': 0})
        coverage['first'] = min(coverage['first'], str(day))
        coverage['last'] = max(coverage['last'], str(day))
        coverage['count'] += 1
        if source and row['source_type'] != source:
            continue
        if not row['matched'] or (start_day and day < start_day):
            continue
        if end_day and day > end_day + timedelta(days=7 if after else 0):
            continue
        late = bool(boundary and (stamp > boundary if cutoff == 'close' else stamp >= boundary))
        if end_day and cutoff == 'close' and day == end_day and not precise:
            uncertain += 1
            # Never pretend a date-only disclosure was public before the close.
            if not after:
                continue
            status = 'uncertain'
        else:
            status = 'after' if late else 'within'
            if late and not after:
                continue
        row.update(published_at=stamp.isoformat() if precise else str(day),
                   local_date=str(day), time_precision='time' if precise else 'date', status=status)
        row.pop('matched', None)
        row['_sort'] = stamp.timestamp()
        result.append(row)
    result.sort(key=lambda r: (r['status'] != 'within', -r['_sort'], r['id']))
    total = len(result)
    items = result[(page-1)*size:page*size]
    # Resolve human publisher names only for the returned page.
    from pipeline.sources import source_names
    named = source_names(conn, [dict(r, id=r['doc_id']) for r in items if r['doc_id'] is not None])
    for r in items:
        fallback = r['source_id'] or r['source_type']
        if fallback.startswith(('http://', 'https://')):
            fallback = urlsplit(fallback).hostname or r['source_type']
        r['publisher'] = (named.get(r['doc_id']) or {}).get('name') or fallback
        r.pop('_sort', None)
        r.pop('source_id', None)
    return dict(items=items, total=total, page=page, size=size, has_more=page*size < total,
                coverage=list(available.values()), undated_count=unknown, uncertain_count=uncertain,
                timezone=str(zone), as_of=now.isoformat())
