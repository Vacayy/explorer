"""Rebuild fixture system timeline from archived PostgreSQL rows."""
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import quote
import json

from models.timeline import TimelineItem, TimelineLink
from pipeline.postgres_snapshot import SNAPSHOT_LOCK_KEY, _insert_batches
from pipeline.timeline import _company_link, _excerpt, utc

# Only read columns used for this view; raw documents and transcript bodies can be large.
FIELDS = {
    'entities': ('id', 'type', 'name', 'aliases'),
    'entity_digests': ('id', 'entity_id', 'period', 'period_start', 'digest', 'doc_count', 'created_at'),
    'source_digests': ('id', 'kind', 'key', 'digest', 'doc_count', 'created_at'),
    'transcripts': ('id', 'raw_doc_id', 'ticker', 'fiscal_year', 'fiscal_period', 'digest', 'fetched_at'),
    'transcript_follow': ('ticker', 'company_name', 'active'),
    'trade_stats': ('hs_code', 'period', 'fetched_at'),
    'trade_follow': ('hs_code', 'item_name', 'group_label', 'active'),
    'narratives': ('id', 'topic', 'version', 'title', 'body', 'doc_count', 'created_at'),
    'reports': ('id', 'anchor_topic', 'title', 'body', 'members_json', 'created_at'),
    'scenarios': ('topic', 'answer', 'question_id', 'created_at'),
}


def rebuild_system_timeline(connection_factory):
    with connection_factory() as conn:
        database, schema = conn.execute('SELECT current_database(),current_schema()').fetchone()
        if database != 'fixture' or not schema or not schema.startswith('refactor_fixture_'):
            raise ValueError('Refusing rebuild outside disposable fixture schema')
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (SNAPSHOT_LOCK_KEY,))
        tables = {}
        for name, fields in FIELDS.items():
            expr = ','.join("'%s',row_data->'%s'" % (field, field) for field in fields)
            tables[name] = [r[0] for r in conn.execute(
                f'SELECT jsonb_build_object({expr}) FROM legacy_snapshot_rows WHERE table_name=%s ORDER BY row_ordinal', (name,))]
        document_ids = {r[0] for r in conn.execute("SELECT (row_data->>'id')::bigint FROM legacy_snapshot_rows WHERE table_name='raw_documents'")}
        entities = {e['id']: e for e in tables['entities']}
        records = []
        def emit(item, stamp, channel, topic, name, preview):
            try:
                occurred = utc(stamp)
                dt = datetime.fromisoformat(occurred)
            except (TypeError, ValueError, AttributeError):
                return
            delta = dt - datetime(1970, 1, 1, tzinfo=timezone.utc)
            millis = ((delta.days*86400+delta.seconds)*1000000+delta.microseconds+500)//1000
            item['occurred_at'] = occurred
            record = TimelineItem(**item)
            records.append((record.id, occurred, millis, channel, topic, name or '', (preview or '')[:180],
                            json.dumps(record.model_dump(mode='json'), ensure_ascii=False)))

        for r in tables['entity_digests']:
            e = entities.get(r['entity_id'])
            if not e or e['type'] != 'company' or not (r['digest'] or '').strip(' '):
                continue
            label = {'1d':'하루','1w':'주간','7d':'7일','1m':'월간'}.get(r['period'], r['period'])
            item = dict(id=f"company:{r['id']}", kind='company', title=f"{e['name']} · {label} 요약", subject=e['name'],
                        body=r['digest'], period=f"{r['period_start']} · {label}", time_label='요약 생성',
                        evidence_count=r['doc_count'], ai_generated=True, to=_company_link(e['name'], e['aliases']))
            emit(item, r['created_at'], f"company:{e['id']}", e['name'], e['name'], r['digest'])
        for r in tables['source_digests']:
            if r['kind'] != 'person' or not (r['digest'] or '').strip(' '):
                continue
            item = dict(id=f"person:{r['id']}", kind='person', title=f"{r['key']} · 인물 업데이트", subject=r['key'],
                        body=r['digest'], time_label='요약 생성', evidence_count=r['doc_count'], ai_generated=True,
                        to=f"/person?name={quote(r['key'], safe='')}")
            emit(item, r['created_at'], f"person:{r['key']}", None, r['key'], r['digest'])
        followed = {r['ticker']: r for r in tables['transcript_follow'] if r['active'] == 1}
        for r in tables['transcripts']:
            f = followed.get(r['ticker'])
            if not f or r['raw_doc_id'] not in document_ids:
                continue
            period = ' '.join(str(v) for v in (r['fiscal_year'], r['fiscal_period']) if v)
            item = dict(id=f"transcript:{r['id']}", kind='transcript', title=f"{f['company_name']} · {period} 컨콜",
                        subject=f['company_name'], body=r['digest'] or '새 컨콜 원문이 수집됐습니다. 요약은 아직 없습니다.',
                        period=f'회계분기 {period}', time_label='수집', evidence_count=1, ai_generated=bool(r['digest']),
                        to=f"/follow/transcripts?t={r['id']}", links=[TimelineLink(label='컨콜 원문', to=f"/doc/{r['raw_doc_id']}")])
            emit(item, r['fetched_at'], f"transcript:{r['ticker']}", None,
                 f"{f['company_name'] if f['company_name'] is not None else r['ticker']} · 컨콜", r['digest'] if r['digest'] is not None else '새 컨콜 원문')
        latest = {}
        for r in tables['trade_stats']:
            if r['period'] is not None and (r['hs_code'] not in latest or r['period'] > latest[r['hs_code']]):
                latest[r['hs_code']] = r['period']
        follows = {r['hs_code']: r for r in tables['trade_follow'] if r['active'] == 1}
        grouped = defaultdict(list)
        for r in tables['trade_stats']:
            f = follows.get(r['hs_code'])
            if f and r['period'] is not None and latest.get(r['hs_code']) == r['period']:
                grouped[r['period']].append((r, f))
        for period, entries in grouped.items():
            entries.sort(key=lambda pair: (pair[1]['group_label'] or '', pair[1]['hs_code']))
            names = ' · '.join(f['item_name'] for _, f in entries[:3])
            item = dict(id=f'trade:{period}', kind='trade', title=f'{period} 수출입 · {len(entries)}개 품목', subject='관심 수출입 품목',
                        body=f"{names}{' 등' if len(entries)>3 else ''}의 월별 통계를 확인할 수 있습니다. 수출·수입 추이와 전년 대비 변화를 비교하세요.",
                        period=f'통계 기준 {period}', time_label='최근 수집', to='/follow/trade',
                        links=[TimelineLink(label=f['item_name'], to=f"/follow/trade?hs={quote(f['hs_code'])}") for _, f in entries[:3]])
            stamps = [r['fetched_at'] for r, _ in entries if r['fetched_at'] is not None]
            emit(item, max(stamps) if stamps else None, 'trade:all', None, '관심 수출입 품목', f'{period} 수출입 통계')
        for r in tables['narratives']:
            if not (r['body'] or '').strip(' '): continue
            item = dict(id=f"narrative:{r['id']}", kind='narrative', title=r['title'] or r['topic'], subject=r['topic'],
                        body=_excerpt(r['body'], '3줄 요약'), period=f"v{r['version']}", time_label='생성',
                        evidence_count=r['doc_count'], ai_generated=True, to=f"/narrative?topic={quote(r['topic'], safe='')}")
            emit(item, r['created_at'], 'narrative:all', r['topic'], 'Explorer · 내러티브', r['title'] or r['topic'])
        for r in tables['reports']:
            if not (r['body'] or '').strip(' '): continue
            try: members = len(json.loads(r['members_json'] or '[]'))
            except (ValueError, TypeError): members = None
            item = dict(id=f"report:{r['id']}", kind='report', title=r['title'] or f"{r['anchor_topic']} 통합 리포트",
                        subject=r['anchor_topic'], body=_excerpt(r['body'], '결론'), time_label='발간', evidence_count=members,
                        ai_generated=True, to=f"/report?topic={quote(r['anchor_topic'], safe='')}")
            emit(item, r['created_at'], 'report:all', r['anchor_topic'], 'Explorer · 리포트', r['title'] or r['anchor_topic'])
        for r in tables['scenarios']:
            if not (r['answer'] or '').strip(' '): continue
            item = dict(id=f"scenario:{r['topic']}", kind='scenario', title=f"{r['topic']} 파급 분석", subject=r['topic'],
                        body=_excerpt(r['answer'], None), time_label='생성', ai_generated=True,
                        to=f"/question/{r['question_id']}" if r['question_id'] else f"/narrative?topic={quote(r['topic'], safe='')}")
            emit(item, r['created_at'], 'scenario:all', r['topic'], 'Explorer · 파급 분석', f"{r['topic']} 파급 분석")
        conn.execute('DELETE FROM timeline_system_projection')
        _insert_batches(conn, 'INSERT INTO timeline_system_projection VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)', records)
        return len(records)
