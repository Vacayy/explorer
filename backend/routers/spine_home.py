"""홈(내 종목 follow-up) API — product-v2.md v2.1.

- calendar: 오늘~7일 이벤트, 내 종목(왓치리스트) 우선 정렬
- watchlist_updates: 왓치리스트 종목의 최근 문서 언급 + 신호 (delta 스트림)
- market_highlights: 전체 최근 신호 (내 종목 업데이트가 적은 날 프론트에서 승격)
"""
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Query
from database import get_connection
from models.spine import CalendarEvent, HomeResponse, SignalItem, WatchlistUpdate

router = APIRouter(prefix="/api/spine/home", tags=["spine"])


@router.get("", response_model=HomeResponse)
def get_home(days: int = Query(3, ge=1, le=14, description="업데이트 스트림 기간")):
    conn = get_connection()
    today = date.today()

    wl = conn.execute("SELECT stock_code, corp_name FROM watchlist").fetchall()
    wl_codes = {r["stock_code"]: r["corp_name"] for r in wl}

    # ① 캘린더: 오늘~7일, 내 종목 우선
    cal_rows = conn.execute("""
        SELECT c.id, c.stock_code, co.corp_name, c.event_type, c.event_date, c.title
        FROM catalysts c LEFT JOIN companies co ON c.corp_code = co.corp_code
        WHERE c.event_date >= ? AND c.event_date <= ?
        ORDER BY c.event_date ASC
    """, (today.isoformat(), (today + timedelta(days=7)).isoformat())).fetchall()
    calendar = sorted(
        [CalendarEvent(
            id=r["id"], stock_code=r["stock_code"], corp_name=r["corp_name"],
            event_type=r["event_type"], event_date=r["event_date"], title=r["title"],
            in_watchlist=r["stock_code"] in wl_codes,
        ) for r in cal_rows],
        key=lambda e: (not e.in_watchlist, e.event_date),
    )

    # ② 왓치리스트 업데이트 스트림 (문서 언급 + 신호)
    updates: list[WatchlistUpdate] = []
    if wl_codes:
        ph = ",".join("?" for _ in wl_codes)
        since_dt = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        for r in conn.execute(f"""
            SELECT DISTINCT e.aliases AS stock_code, e.name AS corp_name,
                   rd.published_at, rd.title, rd.url, rd.source_type
            FROM entity_links el
            JOIN entities e ON el.entity_id = e.id
            JOIN raw_documents rd ON el.doc_id = rd.id
            WHERE el.link_type = 'stock' AND e.type = 'company'
              AND e.aliases IN ({ph}) AND rd.published_at >= ?
            ORDER BY rd.published_at DESC LIMIT 50
        """, [*wl_codes, since_dt]):
            updates.append(WatchlistUpdate(
                kind="document", stock_code=r["stock_code"], corp_name=r["corp_name"],
                occurred_at=r["published_at"], title=r["title"] or "",
                url=r["url"], source_type=r["source_type"], signal_type=None))
        for r in conn.execute(f"""
            SELECT s.signal_type, s.date, s.payload_json,
                   e.aliases AS stock_code, e.name AS corp_name
            FROM signals s JOIN entities e ON s.entity_id = e.id
            WHERE e.aliases IN ({ph}) AND s.date >= ?
            ORDER BY s.date DESC LIMIT 20
        """, [*wl_codes, (today - timedelta(days=days)).isoformat()]):
            p = json.loads(r["payload_json"] or "{}")
            updates.append(WatchlistUpdate(
                kind="signal", stock_code=r["stock_code"], corp_name=r["corp_name"],
                occurred_at=r["date"],
                title=f"언급 급증: 최근 7일 {p.get('count_7d', '?')}회",
                url=None, source_type=None, signal_type=r["signal_type"]))
        updates.sort(key=lambda u: u.occurred_at, reverse=True)

    # ③ 시장 하이라이트: 최근 신호 전체 (빈 날 승격용)
    highlights = [SignalItem(
        id=r["id"], signal_type=r["signal_type"], entity_id=r["entity_id"],
        entity_name=r["entity_name"], stock_code=r["stock_code"], date=r["date"],
        payload=json.loads(r["payload_json"] or "{}"),
        interpretation=r["interpretation"], interpretation_model=r["interpretation_model"],
    ) for r in conn.execute("""
        SELECT s.id, s.signal_type, s.entity_id, s.date, s.payload_json,
               s.interpretation, s.interpretation_model,
               e.name AS entity_name, e.aliases AS stock_code
        FROM signals s JOIN entities e ON s.entity_id = e.id
        WHERE s.date >= ?
        ORDER BY s.date DESC, s.id DESC LIMIT 10
    """, ((today - timedelta(days=7)).isoformat(),))]
    conn.close()

    return HomeResponse(
        calendar=calendar,
        watchlist_updates=updates[:30],
        market_highlights=highlights,
        watchlist_empty=not wl_codes,
        as_of=datetime.now(timezone.utc).isoformat(),
    )
