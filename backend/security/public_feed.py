"""Source navigation over reviewed publication snapshots, never subscriptions/read state."""
from datetime import datetime, timezone
from urllib.parse import urlsplit

from security.public_documents import DocumentUnavailable, ListingBudgetExceeded, ReadBudget


def channel_for(conn, row):
    """Resolve only this document's source. The result is part of its approval fingerprint."""
    kind = row['source_type'] or ''
    if not isinstance(kind, str) or (row['url'] is not None and not isinstance(row['url'], str)):
        raise DocumentUnavailable()
    name = key = None
    if kind in {'telegram', 'youtube'}:
        source = conn.execute('SELECT substr(source_id,1,2049) FROM raw_documents WHERE id=?', (row['id'],)).fetchone()[0] or ''
        if not isinstance(source, str) or len(source) > 2048:
            raise DocumentUnavailable()
        key = source.split('/')[0] if '/' in source else None
        if key:
            sql = ('SELECT substr(display_name,1,513) FROM telegram_channels WHERE channel_name=?' if kind == 'telegram'
                   else 'SELECT substr(title,1,513) FROM youtube_channels WHERE channel_id=?')
            found = conn.execute(sql, (key,)).fetchone()
            name = (found[0] if found else None) or key
    elif kind == 'blog':
        from pipeline.urls import url_belongs
        candidates = conn.execute('SELECT substr(url,1,2049),substr(blog_name,1,513) FROM blog_sources ORDER BY length(url) DESC LIMIT 1001').fetchall()
        if len(candidates) > 1000:
            raise DocumentUnavailable()
        for prefix in (True, False):
            match = next((r for r in candidates if url_belongs(row['url'] or '', r[0], prefix_only=prefix)), None)
            if match:
                key, name = match[0], match[1] or match[0]
                break
    if not key and row['url']:
        try:
            parsed = urlsplit(row['url'])
            if parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username and not parsed.password:
                key = name = parsed.hostname
        except ValueError:
            pass
    if not key:
        return None
    if not isinstance(key, str) or not isinstance(name, str) or len(key) > 2048 or len(name) > 512:
        raise DocumentUnavailable()
    return {'id': kind + ':' + key, 'name': name, 'platform': kind}


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def feed_metadata(document):
    source = document.channel
    return dict(channel=source.id if source else 'unassigned', name=source.name if source else '수집 자료',
                platform=source.platform if source else 'other', title=document.title,
                published_at=document.published_at, sort_at=timestamp(document.published_at).isoformat())


def public_feed(service, *, channel='', platform='all', topic='', page=1, until=None):
    # The directory reads only metadata saved by the same approval transaction.
    # It does not re-read every source body/attachment on each page request.
    # Metadata describes the approved revision; current body is revalidated below.
    import json
    cutoff = until or datetime.now(timezone.utc)
    with service.store.connection(readonly=True) as conn:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        base = "status='approved' AND feed_metadata IS NOT NULL AND json_extract(feed_metadata,'$.sort_at')<=?"
        directory = conn.execute(f"""WITH approved AS (
            SELECT feed_metadata, json_extract(feed_metadata,'$.channel') channel,
                count(*) OVER (PARTITION BY json_extract(feed_metadata,'$.channel')) count,
                row_number() OVER (PARTITION BY json_extract(feed_metadata,'$.channel')
                    ORDER BY json_extract(feed_metadata,'$.sort_at') DESC,doc_id DESC) rank
            FROM publications WHERE {base})
            SELECT feed_metadata,count FROM approved WHERE rank=1
            ORDER BY json_extract(feed_metadata,'$.sort_at') DESC,channel""", (cutoff.isoformat(),)).fetchall()
        channels = []
        for row in directory:
            metadata = json.loads(row['feed_metadata'])
            channels.append(dict(id=metadata['channel'],name=metadata['name'],platform=metadata['platform'],count=row['count'],
                                 latest_at=metadata['published_at'],preview=metadata['title']))
        # Topic uses reviewed titles here; full body search remains the existing
        # bounded public document search. It never searches private FTS.
        conditions = base + " AND (?='' OR json_extract(feed_metadata,'$.channel')=?) AND (?='all' OR json_extract(feed_metadata,'$.platform')=?)"
        args = [cutoff.isoformat(), channel,channel,platform,platform]
        if topic.strip():
            conditions += " AND instr(lower(json_extract(feed_metadata,'$.title')),lower(?))>0"
            args.append(topic.strip())
        rows = conn.execute(f"""SELECT doc_id FROM publications WHERE {conditions}
            ORDER BY json_extract(feed_metadata,'$.sort_at') DESC,doc_id DESC LIMIT 21 OFFSET ?""", (*args,(page-1)*20)).fetchall()
    items, fingerprints = [], {}
    budget = ReadBudget()
    for row in rows[:20]:
        try:
            snapshot = service.published(row['doc_id'], budget=budget)
        except DocumentUnavailable:
            continue
        doc = snapshot.document
        items.append(dict(id=doc.id,title=doc.title,source_type=doc.source_type,published_at=doc.published_at,
                          snippet=' '.join(doc.content.split())[:240]))
        fingerprints[doc.id] = snapshot.fingerprint
    items = [item for item in items if (record := service.store.get(item['id']))
             and record['status']=='approved' and record['fingerprint']==fingerprints[item['id']]]
    return dict(channels=channels,items=items,page=page,has_more=len(rows)>20,until=cutoff.isoformat())
