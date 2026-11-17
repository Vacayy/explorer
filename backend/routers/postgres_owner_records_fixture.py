"""Loopback-only owner follows, prediction pins, feed read marks, bookmarks, tracker conditions and
call-follow pins/additions, knowledge review decisions, trade-item follows, narrative-candidate decisions and source switches/additions on the PG ledger.

Same request/response shapes and errors as the legacy routes. The follow list
and feed read marks read the ledger directly; legacy reads (prediction cards)
see it through the projection's per-connection TEMP shadows, so writes show at once. Never serve beyond the
private loopback gateway; external exposure needs the owner gate first.
"""
import json
from contextlib import contextmanager

from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.routing import APIRoute

from models.kalshi import KalshiPinBody, KalshiPinResult
from models.timeline import MarkAllReadResponse
from pipeline.timeline import utc
from pipeline import postgres_owner_records_fixture as records
from routers.spine_feed import MarkAllReadRequest, MarkReadRequest
from routers.company_profile import ProfileRequest
from routers.spine_knowledge import InjectRequest, InjectResponse
from routers.spine_follows import FollowedEntity, FollowRequest
from routers.spine_saved import NoteRequest, SavedItem, SaveRequest
from routers.spine_tracker import Code
from models.market_today import CandidateAction
from routers.blog_feed import ToggleSourceRequest
from routers.spine_sources import AddBlogRequest, AddTelegramRequest, AddYouTubeRequest, CollectToggle
from routers.telegram_feed import ToggleChannelRequest
from routers.spine_trade import FollowReq as TradeFollowReq
from routers.spine_transcript import FollowReq, PinReq
from models.tracker import TrackerCondition, TrackerConditionIn, TrackerConditionPatch


def create_router(factory, timeline, projection=None):
    router = APIRouter()

    def connection():
        conn = factory()
        try:
            records.owner_account(conn)
        except LookupError:
            conn.close()
            raise HTTPException(503, 'Owner records unavailable') from None
        return conn

    @router.get('/api/spine/follows', response_model=list[FollowedEntity])
    def list_follows():
        with connection() as conn:
            return records.follows(conn)

    @router.post('/api/spine/follows', response_model=FollowedEntity, status_code=201)
    def add_follow(body: FollowRequest):
        if not body.entity_id and not (body.type and body.name):
            raise HTTPException(400, 'entity_id 또는 (type, name) 필요')
        with connection() as conn:
            row = (records.entity(conn, ident=body.entity_id) if body.entity_id
                   else records.entity(conn, kind=body.type, name=body.name))
            if not row:
                raise HTTPException(404, '엔티티를 찾을 수 없습니다')
            records.follow(conn, int(row['id']))
        return FollowedEntity(entity_id=int(row['id']), type=row['type'], name=row['name'])

    @router.delete('/api/spine/follows/{entity_id}', status_code=204)
    def remove_follow(entity_id: int):
        with connection() as conn:
            records.unfollow(conn, entity_id)

    @router.post('/api/spine/home/predictions/{event_ticker}/pin', response_model=KalshiPinResult)
    def prediction_pin(body: KalshiPinBody, event_ticker: str = Path(..., pattern=r'^[A-Za-z0-9._-]{1,80}$')):
        with connection() as conn:
            return {'event_ticker': event_ticker, 'pinned': records.set_pin(conn, event_ticker, body.series_ticker, body.pinned)}

    @router.post('/api/spine/feed/channels/read')
    def mark_channel_read(body: MarkReadRequest):
        if not body.channel or len(body.channel) > 300:
            raise HTTPException(400, 'channel required')
        try:
            stamp = utc(body.read_until)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        with connection() as conn:
            return {'channel': body.channel, 'read_until': records.mark_read(conn, body.channel, stamp)}

    @router.post('/api/spine/feed/channels/read-all', response_model=MarkAllReadResponse)
    def mark_all_channels_read(body: MarkAllReadRequest):
        try:
            stamp = utc(body.read_until)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        # Same targets as the legacy rule: human sources in scope with unread items up to read_until.
        targets = [c for c in timeline.channels(until=stamp, include_owner_read_state=True).items
                   if c.platform != 'system' and (body.platform == 'all' or c.platform == body.platform) and c.unread > 0]
        with connection() as conn:
            for c in targets:
                records.mark_read(conn, c.id, stamp)
        return {'platform': body.platform, 'read_until': stamp, 'channels': len(targets), 'marked': sum(c.unread for c in targets)}

    @contextmanager
    def member():
        """A saved-items ledger is the requester's own (records.requester_account)."""
        from pipeline.postgres_principals import PrincipalRequired
        try:
            with connection() as conn:
                yield conn
        except PrincipalRequired:
            raise HTTPException(401, 'Authentication required') from None

    @router.post('/api/spine/saved', response_model=SavedItem, status_code=201)
    def add_saved(body: SaveRequest):
        if body.kind not in ('company', 'doc', 'narrative', 'report', 'chat'):
            raise HTTPException(400, '알 수 없는 kind')
        with member() as conn:
            return records.save(conn, body)

    @router.patch('/api/spine/saved/{item_id}', response_model=SavedItem)
    def update_note(item_id: int, body: NoteRequest):
        with member() as conn:
            row = records.update_saved_note(conn, item_id, body.note)
        if row is None:
            raise HTTPException(404, '저장 항목을 찾을 수 없습니다')
        return row

    @router.delete('/api/spine/saved/{item_id}', status_code=204)
    def remove_saved(item_id: int):
        with member() as conn:
            records.remove_saved(conn, item_id)

    @router.post('/api/spine/tracker/{code}/conditions', response_model=TrackerCondition)
    def condition_add(body: TrackerConditionIn, code: str = Code):
        if body.kind.startswith('price_') and not body.level:
            raise HTTPException(422, '가격 조건에는 기준가가 필요합니다')
        if body.kind.endswith('_ma') and not body.ma:
            raise HTTPException(422, '이평선 조건에는 N일이 필요합니다')
        import database
        from routers.spine_tracker import _check
        legacy = database.get_connection()  # the projection: same stock lookup as before
        try:
            _check(legacy, code)
        finally:
            legacy.close()
        with connection() as conn:
            return records.add_tracker_condition(conn, code, body)

    @router.patch('/api/spine/tracker/conditions/{cid}', response_model=TrackerCondition)
    def condition_patch(cid: int, body: TrackerConditionPatch):
        with connection() as conn:
            row = records.patch_tracker_condition(conn, cid, {k: v for k, v in body.model_dump().items() if v is not None})
        if not row:
            raise HTTPException(404, '조건 없음')
        return row

    @router.delete('/api/spine/tracker/conditions/{cid}')
    def condition_delete(cid: int):
        with connection() as conn:
            records.delete_tracker_condition(conn, cid)
        return {'deleted': cid}

    @router.post('/api/spine/transcript/core/pin')
    def pin_core(body: PinReq):
        import database
        ticker = body.ticker.upper()
        legacy = database.get_connection()  # the projection: collected rows with the owner's additions
        try:
            followed = legacy.execute('SELECT 1 FROM transcript_follow WHERE ticker=?', (ticker,)).fetchone()
        finally:
            legacy.close()
        if not followed:
            raise HTTPException(404, '팔로우하지 않는 종목입니다')
        with connection() as conn:
            records.set_core_pin(conn, ticker, body.pinned)
        return {'ticker': ticker, 'pinned': body.pinned}

    def candidate(tag):
        import database
        legacy = database.get_connection()  # the projection, with earlier decisions applied
        try:
            row = legacy.execute('SELECT * FROM narrative_candidates WHERE tag=?', (tag,)).fetchone()
            return dict(row) if row else None
        finally:
            legacy.close()

    @router.post('/api/spine/narrative-candidates/{tag}/approve', response_model=CandidateAction)
    def approve_candidate(tag: str = Path(..., max_length=80)):
        # Same decision as market_today_links.approve, including a merge's immediate re-linking of past sessions.
        row = candidate(tag)
        if not row or row['status'] != 'pending':
            raise HTTPException(409, '지금 처리할 수 있는 후보가 아닙니다')
        detail = json.loads(row['detail_json'] or '{}')
        merge = detail.get('merge_into')
        mode, aliases = ('merge', detail.get('tags', [])[:2]) if merge else ('new', None)
        topic = merge['topic'] if merge else (detail.get('tags') or [row['name']])[0]
        with connection() as conn:
            records.decide_narrative(conn, tag, 'approved', narrative_topic=topic, mode=mode, alias_tags=aliases)
            sessions = [session['mt_id'] for session in json.loads(row['sessions_json'] or '[]')]
            if merge and sessions:
                import database
                from pipeline.postgres_collector_bridge import relink_market_today
                relink_market_today(conn, database.DB_PATH, sessions)
        return {'tag': tag, 'status': 'approved', 'mode': mode, 'narrative_topic': topic, 'dismissed_until': None}

    @router.post('/api/spine/narrative-candidates/{tag}/dismiss', response_model=CandidateAction)
    def dismiss_candidate(tag: str = Path(..., max_length=80)):
        from datetime import timedelta
        from pipeline.market_today_links import DISMISS_DAYS, _today_kst
        row = candidate(tag)
        if not row or row['status'] not in ('pending', 'watching'):
            raise HTTPException(409, '지금 처리할 수 있는 후보가 아닙니다')
        until = (_today_kst() + timedelta(days=DISMISS_DAYS)).isoformat()
        with connection() as conn:
            records.decide_narrative(conn, tag, 'dismissed', dismissed_until=until)
        return {'tag': tag, 'status': 'dismissed', 'mode': None, 'narrative_topic': None, 'dismissed_until': until}

    def source_row(table, where, value):
        import database
        legacy = database.get_connection()  # the projection, with earlier switches applied
        try:
            row = legacy.execute(f'SELECT * FROM {table} WHERE {where}=?', (value,)).fetchone()
            return dict(row) if row else None
        finally:
            legacy.close()

    @router.put('/api/blog/sources/{source_id}/toggle')
    def toggle_blog(source_id: int, body: ToggleSourceRequest):
        row = source_row('blog_sources', 'id', source_id)
        if not row:
            raise HTTPException(404, '블로그 소스를 찾을 수 없습니다')
        with connection() as conn:
            records.set_source(conn, 'blog', row['url'], is_active=1 if body.is_active else 0)
        row['is_active'] = 1 if body.is_active else 0  # same columns, same order as the legacy response
        return {key: row[key] for key in ('id', 'url', 'platform', 'blog_name', 'is_active', 'last_fetched_at', 'added_at')}

    @router.put('/api/telegram/channels/{channel_id}/toggle')
    def toggle_telegram(channel_id: int, body: ToggleChannelRequest):
        row = source_row('telegram_channels', 'id', channel_id)
        if not row:
            raise HTTPException(404, '채널을 찾을 수 없습니다')
        with connection() as conn:
            records.set_source(conn, 'telegram', row['channel_name'], is_active=1 if body.is_active else 0)
        row['is_active'] = 1 if body.is_active else 0
        return {key: row[key] for key in ('id', 'channel_name', 'display_name', 'is_active', 'last_fetched_at', 'added_at')}

    @router.patch('/api/spine/sources/youtube/{channel_id}')
    def toggle_youtube(channel_id: str, is_active: bool):
        # Like the legacy UPDATE, an unknown channel is answered the same way and changes nothing.
        if source_row('youtube_channels', 'channel_id', channel_id):
            with connection() as conn:
                records.set_source(conn, 'youtube', channel_id, is_active=int(is_active))
        return {'channel_id': channel_id, 'is_active': is_active}

    # Adding a source: the same validation and external checks as the legacy routes, recorded in the
    # owner ledger. The legacy background collection is not started here (single writer): the source is
    # collected by the next collector run, and the response says so.
    NEXT_RUN = '다음 수집 회차에 수집'

    @router.post('/api/spine/sources/telegram', status_code=201)
    def add_telegram(body: AddTelegramRequest):
        import re
        from services.telegram_service import get_channel_display_name, scrape_channel
        channel = re.sub(r'^https?://t\.me/(s/)?', '', body.channel.strip()).lstrip('@').strip('/')
        if not re.fullmatch(r'[A-Za-z0-9_]{3,64}', channel):
            raise HTTPException(400, '채널명 형식이 올바르지 않습니다 (예: cahier_de_market)')
        messages = scrape_channel(channel)
        if not messages:
            raise HTTPException(422, '공개 프리뷰를 읽을 수 없는 채널입니다 (비공개이거나 프리뷰 비활성)')
        display_name = get_channel_display_name(channel)
        if source_row('telegram_channels', 'channel_name', channel):
            raise HTTPException(409, '이미 등록된 채널입니다')
        with connection() as conn:
            records.add_source(conn, 'telegram', channel, {'channel_name': channel, 'display_name': display_name})
        return {'channel': channel, 'preview_messages': len(messages), 'note': NEXT_RUN}

    @router.post('/api/spine/sources/blog', status_code=201)
    def add_blog(body: AddBlogRequest):
        from routers.spine_sources import normalize_naver_blog
        from services.blog_service import detect_platform_and_feed_url, fetch_blog_author, verify_and_fetch
        url = body.url.strip().rstrip('/')
        if 'youtube.com' in url or 'youtu.be' in url:
            raise HTTPException(422, '유튜브 주소는 유튜브 카드에서 추가해 주세요 (채널 @handle·URL 또는 영상 URL).')
        if not url.startswith('http'):
            url = f'https://{url}'
        url = normalize_naver_blog(url.replace('://m.blog.naver.com/', '://blog.naver.com/'))
        platform, feed_url = detect_platform_and_feed_url(url)
        try:
            posts, blog_name = verify_and_fetch(feed_url)
        except Exception as e:
            raise HTTPException(422, f'RSS 피드를 읽을 수 없습니다: {e}')
        author = fetch_blog_author(url, posts)
        if source_row('blog_sources', 'url', url):
            raise HTTPException(409, '이미 등록된 블로그입니다')
        with connection() as conn:
            records.add_source(conn, 'blog', url, {'url': url, 'platform': platform, 'blog_name': blog_name, 'author': author})
        return {'url': url, 'blog_name': blog_name, 'author': author, 'platform': platform,
                'preview_posts': len(posts), 'note': NEXT_RUN}

    @router.post('/api/spine/sources/youtube', status_code=201)
    def add_youtube(body: AddYouTubeRequest):
        from pipeline.connectors.youtube import parse_video_id, resolve_channel_id
        s = body.input.strip()
        if parse_video_id(s) if ('watch' in s or 'youtu.be' in s or '/live/' in s or '/shorts/' in s or len(s) == 11) else None:
            # A single video is collected on the spot in the legacy route; the candidate does not collect.
            raise HTTPException(405, '영상 단건 수집은 후보에서 하지 않습니다')
        resolved = resolve_channel_id(s)
        if not resolved:
            raise HTTPException(422, '채널을 찾을 수 없습니다 (채널 URL 또는 @handle을 입력하세요)')
        channel_id, title = resolved
        if source_row('youtube_channels', 'channel_id', channel_id):
            raise HTTPException(409, '이미 구독 중인 채널입니다')
        with connection() as conn:
            records.add_source(conn, 'youtube', channel_id, {'channel_id': channel_id,
                               'handle': s if s.startswith('@') else None, 'title': title})
        return {'kind': 'channel', 'channel_id': channel_id, 'title': title, 'note': f'구독 완료 — {NEXT_RUN}'}

    @router.post('/api/spine/sources/collect')
    def set_collect(body: CollectToggle):
        table, column = records.SOURCE_TABLES.get(body.kind, (None, None))
        if not table:
            raise HTTPException(400, '알 수 없는 kind')
        if not source_row(table, column, body.key):
            raise HTTPException(404, '해당 소스를 찾을 수 없습니다')
        with connection() as conn:
            records.set_source(conn, body.kind, body.key, collect_enabled=1 if body.enabled else 0)
        return {'kind': body.kind, 'key': body.key, 'collect_enabled': body.enabled}

    @router.post('/api/spine/trade/follow', status_code=201)
    def upsert_trade_follow(body: TradeFollowReq):
        with connection() as conn:
            records.upsert_trade_follow(conn, body.hs_code, body.item_name or body.hs_code, body.group_label, 1 if body.active else 0)
        return {'hs_code': body.hs_code, 'active': body.active}

    @router.post('/api/spine/knowledge/items/{knowledge_id}/approve')
    def approve_knowledge(knowledge_id: int):
        import database
        legacy = database.get_connection()  # the projection, with earlier decisions applied
        try:
            if not legacy.execute("SELECT id FROM knowledge WHERE id=? AND review_status IN ('proposed','held')",
                                  (knowledge_id,)).fetchone():
                raise HTTPException(404, '대기 중인 지식이 없습니다')
            independent = legacy.execute("SELECT count(*) FROM knowledge_evidence WHERE knowledge_id=? AND stance='support' "
                                         "AND independent=1", (knowledge_id,)).fetchone()[0]
        finally:
            legacy.close()
        epistemic = 'corroborated' if independent >= 2 else 'observed'
        with connection() as conn:
            records.review_knowledge(conn, knowledge_id, 'active', epistemic)
        if projection is not None:
            falsify(knowledge_id)
        return {'id': knowledge_id, 'epistemic_status': epistemic}

    @router.post('/api/spine/company-profile/{code}')
    def build_company_profile(code: str, body: ProfileRequest, market: Literal['kr', 'us'] = Query('kr')):
        # The legacy route (web research model call, DART text for KR) as a private-copy computation: the
        # report row and its source documents are published like collected rows. The candidate's network
        # guard blocks in-process fetches (the DART text is then reported as a gap, as the legacy code does).
        from pipeline import company_profile as cp, postgres_copy_compute
        from routers.company_profile import _company
        from routers.postgres_legacy_read_fixture import _offline
        if projection is None:
            raise HTTPException(503, 'Company profile unavailable')
        code = code.upper() if market == 'us' else code
        conn = cp.connect()
        try:
            name, sector = _company(conn, code, market)
        finally:
            conn.close()
        offline = _offline.set(True)
        try:
            profile, reused = postgres_copy_compute.run(
                projection, factory,
                lambda work: cp.ensure_profile(code, name, sector, body.reason, force=body.force, market=market),
                results={'company_profiles': ('id', 'company_profiles')}, source=f'POST /api/spine/company-profile/{code}')
        except cp.ProfileUnavailable as exc:
            raise HTTPException(502, str(exc)) from exc
        except Exception as exc:  # as legacy: model and network failures are shown, not hidden
            raise HTTPException(502, f'웹 조사를 마치지 못했습니다: {str(exc)[:200]}') from exc
        finally:
            _offline.reset(offline)
        return {'profile': profile, 'reused': reused, 'reuse_hours': cp.REUSE_HOURS, 'market': market}

    @router.post('/api/spine/knowledge', response_model=InjectResponse, status_code=201)
    def inject_knowledge(body: InjectRequest):
        # The legacy injection on a private projection copy; the note goes to the candidate-only notes folder.
        from pipeline.postgres_knowledge_inject import inject
        from routers.postgres_legacy_read_fixture import _offline
        if projection is None:
            raise HTTPException(503, 'Knowledge injection unavailable')
        offline = _offline.set(True)  # in-process network guard; model calls run as CLI subprocesses
        try:
            return InjectResponse(**inject(projection, factory, '/app/vault/notes/injected', body.content, body.epistemic,
                                           body.rationale, body.source))
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            _offline.reset(offline)

    def falsify(knowledge_id):
        # As the legacy route: falsifiers from the moment knowledge becomes active (one model call, idempotent),
        # run unchanged on a writable copy of its table and kept as computed rows.
        from pipeline import postgres_owner_overrides as overrides
        from pipeline.falsifiers import generate_falsifiers
        from routers.postgres_legacy_read_fixture import _offline
        offline = _offline.set(True)
        conn, _ = projection.write_connection(('knowledge_falsifiers',))
        try:
            statement = conn.execute('SELECT statement FROM knowledge WHERE id=?', (knowledge_id,)).fetchone()['statement']
            before = overrides.rows(conn)
            generate_falsifiers(conn, knowledge_id, statement)
            with factory() as pg, pg.transaction():
                overrides.apply(pg, before, overrides.rows(conn), source=f'POST /api/spine/knowledge/items/{knowledge_id}/approve')
        finally:
            conn.close()
            _offline.reset(offline)

    @router.post('/api/spine/knowledge/items/{knowledge_id}/reject')
    def reject_knowledge(knowledge_id: int):
        import database
        legacy = database.get_connection()
        try:
            known = legacy.execute('SELECT 1 FROM knowledge WHERE id=?', (knowledge_id,)).fetchone()
        finally:
            legacy.close()
        if known:  # the legacy UPDATE also answers 200 for an unknown id
            with connection() as conn:
                records.review_knowledge(conn, knowledge_id, 'rejected')
        return {'id': knowledge_id}

    @router.post('/api/spine/transcript/follow', status_code=201)
    def upsert_follow(body: FollowReq):
        ticker = body.ticker.upper()
        with connection() as conn:
            records.upsert_transcript_follow(conn, ticker, body.company_name or ticker, body.group_label, 1 if body.active else 0)
        return {'ticker': ticker, 'active': body.active}

    return router


def install(app, factory, timeline, projection=None):
    """Put the ledger routes ahead of the read-only legacy routes with the same path."""
    router = create_router(factory, timeline, projection)
    owned = {(route.path, method) for route in router.routes for method in route.methods}
    app.router.routes[:] = [route for route in app.router.routes
                            if not (isinstance(route, APIRoute) and any((route.path, m) in owned for m in route.methods))]
    app.router.routes[0:0] = list(router.routes)
