"""홈(내 종목 follow-up) API — product-v2.md v2.1.

- calendar: 오늘~7일 이벤트, 내 종목(왓치리스트) 우선 정렬
- watchlist_updates: 왓치리스트 종목의 최근 문서 언급 + 신호 (delta 스트림)
- market_highlights: 전체 최근 신호 (내 종목 업데이트가 적은 날 프론트에서 승격)
"""
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel
from database import get_connection
from models.spine import BriefItem, CalendarEvent, HomeFollow, HomeResponse, SignalItem, WatchlistUpdate

router = APIRouter(prefix="/api/spine/home", tags=["spine"])


class AiActivityItem(BaseModel):
    type: str            # narrative | mega | report | scenario | digest
    title: str
    topic: str
    code: str | None = None   # digest면 종목코드(analyze 링크용)
    created_at: str


@router.get("/ai-activity", response_model=list[AiActivityItem])
def ai_activity(days: int = Query(7, ge=1, le=30), limit: int = Query(30, ge=1, le=100)):
    """지난 N일간 AI가 자동/승인 생성한 산출물 — 내러티브·리포트·파급·다이제스트, 최신순 통합 피드."""
    conn = get_connection()
    since = f"-{days} days"
    items: list[dict] = []
    for r in conn.execute(
        "SELECT topic, title, created_at, COALESCE(kind,'topic') kind FROM narratives "
        "WHERE created_at >= datetime('now', ?)", (since,)):
        items.append({"type": "mega" if r["kind"] == "mega" else "narrative",
                      "title": r["title"] or r["topic"], "topic": r["topic"], "created_at": r["created_at"]})
    for r in conn.execute(
        "SELECT anchor_topic, title, created_at FROM reports WHERE created_at >= datetime('now', ?)", (since,)):
        items.append({"type": "report", "title": r["title"] or f"{r['anchor_topic']} 리포트",
                      "topic": r["anchor_topic"], "created_at": r["created_at"]})
    for r in conn.execute(
        "SELECT topic, created_at FROM scenarios WHERE created_at >= datetime('now', ?)", (since,)):
        items.append({"type": "scenario", "title": f"{r['topic']} 파급 분석",
                      "topic": r["topic"], "created_at": r["created_at"]})
    for r in conn.execute(
        "SELECT e.name, e.aliases code, d.period, d.created_at FROM entity_digests d "
        "JOIN entities e ON e.id=d.entity_id "
        "WHERE d.created_at >= datetime('now', ?) AND e.aliases IS NOT NULL", (since,)):
        items.append({"type": "digest", "title": f"{r['name']} {r['period'].upper()} 요약",
                      "topic": r["name"], "code": r["code"], "created_at": r["created_at"]})
    conn.close()
    items.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return [AiActivityItem(**x) for x in items[:limit]]


@router.get("", response_model=HomeResponse)
def get_home(days: int = Query(3, ge=1, le=14, description="업데이트 스트림 기간")):
    conn = get_connection()
    today = date.today()

    wl = conn.execute("SELECT stock_code, corp_name FROM watchlist").fetchall()
    wl_codes = {r["stock_code"]: r["corp_name"] for r in wl}

    # ⓪ 기계가 먼저 말하는 3줄 — 저장된 재료의 결정적 조합 (추가 LLM 호출 없음)
    #    우선순위: 내 종목/팔로우 insight > 시장 insight > 오늘 기업활동 > 오늘 신호
    briefing: list[BriefItem] = []
    # 소스 경고 최우선 — '조용함'이 수집 고장이면 그것부터 알려야 한다
    from routers.spine_sources import compute_source_health
    dead = [i for i in compute_source_health(conn) if i["warning"]]
    if dead:
        names = ", ".join(i["name"] for i in dead[:3])
        briefing.append(BriefItem(
            kind="warning",
            text=f"소스 {len(dead)}곳 7일간 유입 없음 — {names}",
            to="/feed"))

    # 지식 충돌 (K2, E-3): 최근 24h 내 contested 전환분 중 activation 최고 1건만
    contested = conn.execute("""
        SELECT k.id, k.statement,
               (SELECT count(*) FROM knowledge_evidence
                WHERE knowledge_id=k.id AND stance='refute') ref
        FROM knowledge k
        WHERE k.epistemic_status='contested' AND k.review_status='active'
          AND k.contested_at >= datetime('now', '-1 day')""").fetchall()
    if contested:
        if len(contested) > 1:
            from pipeline.knowledge_recall import _load_active, _score
            acts = {i["id"]: _score(i) for i in _load_active(conn)}
            contested = sorted(contested, key=lambda r: acts.get(r["id"], 0), reverse=True)
        top = contested[0]
        briefing.append(BriefItem(
            kind="conflict",
            text=f'지식 충돌 — "{top["statement"][:70]}…" 반박 증거 {top["ref"]}건 누적',
            to="/knowledge"))

    # 가설 확인 (K3): 내가 주입한 지식이 기계 관측으로 corroborated 승격 — 24h 내
    confirmed = conn.execute("""
        SELECT k.statement,
               (SELECT count(*) FROM knowledge_evidence
                WHERE knowledge_id=k.id AND stance='support' AND independent=1) ind
        FROM knowledge k
        WHERE k.model='user' AND k.epistemic_status='corroborated'
          AND k.corroborated_at >= datetime('now', '-1 day')
        ORDER BY k.corroborated_at DESC LIMIT 1""").fetchone()
    if confirmed:
        briefing.append(BriefItem(
            kind="confirmed",
            text=f'가설 확인 — "{confirmed["statement"][:70]}…" 독립 관측 {confirmed["ind"]}건이 지지',
            to="/knowledge"))

    ins_rows = conn.execute("""
        SELECT e.name, e.aliases stock_code, d.insights, d.period_start
        FROM entity_digests d JOIN entities e ON d.entity_id = e.id
        WHERE d.period='1d' AND d.insights IS NOT NULL
          AND d.period_start >= date('now', '-1 day')
        ORDER BY (e.aliases IN (SELECT stock_code FROM watchlist)) DESC, d.period_start DESC
        LIMIT 4
    """).fetchall()
    for r in ins_rows[:2]:
        briefing.append(BriefItem(
            kind="insight",
            text=f"{r['name']} — {r['insights'][:90]}",
            to=f"/analyze/{r['stock_code']}/mentions" if r["stock_code"] else "/feed"))
    act = conn.execute("""
        SELECT corp_name, action_type FROM corporate_actions
        WHERE rcept_dt = strftime('%Y%m%d', 'now', 'localtime')
        ORDER BY market_cap DESC LIMIT 1""").fetchone()
    if act and len(briefing) < 3:
        briefing.append(BriefItem(kind="action",
            text=f"{act['corp_name']} {act['action_type']} 공시 접수", to="/actions"))
    if len(briefing) < 3:
        sig = conn.execute("""
            SELECT s.signal_type, s.payload_json, e.name, e.aliases stock_code
            FROM signals s JOIN entities e ON s.entity_id = e.id
            WHERE s.date >= date('now', '-1 day')
            ORDER BY s.date DESC, s.id DESC LIMIT 2""").fetchall()
        for r in sig[:3 - len(briefing)]:
            p_ = json.loads(r["payload_json"] or "{}")
            if r["signal_type"] == "high_52w":
                text = f"{r['name']} 52주 신고가 경신 (+{p_.get('breakout_pct')}%)"
            else:
                text = f"{r['name']} 언급 급증 — 7일 {p_.get('count_7d')}회"
            briefing.append(BriefItem(kind="signal", text=text,
                to=f"/analyze/{r['stock_code']}/mentions" if r["stock_code"] else "/explore"))

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

    # ② 업데이트 스트림 = 왓치리스트 종목 + 팔로우 엔티티 (섹터·테마)
    follows_rows = conn.execute("""
        SELECT e.id, e.type, e.name FROM follows f JOIN entities e ON f.entity_id = e.id
        ORDER BY f.created_at""").fetchall()
    follows = [HomeFollow(entity_id=r["id"], type=r["type"], name=r["name"]) for r in follows_rows]

    updates: list[WatchlistUpdate] = []
    seen_docs: set[int] = set()
    since_dt = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    if wl_codes:
        ph = ",".join("?" for _ in wl_codes)
        for r in conn.execute(f"""
            SELECT DISTINCT rd.id doc_id, e.aliases AS stock_code, e.name AS corp_name,
                   rd.published_at, rd.title, rd.url, rd.source_type
            FROM entity_links el
            JOIN entities e ON el.entity_id = e.id
            JOIN raw_documents rd ON el.doc_id = rd.id
            WHERE el.link_type = 'stock' AND e.type = 'company'
              AND e.aliases IN ({ph}) AND rd.published_at >= ?
            ORDER BY rd.published_at DESC LIMIT 50
        """, [*wl_codes, since_dt]):
            seen_docs.add(r["doc_id"])
            updates.append(WatchlistUpdate(
                kind="document", doc_id=r["doc_id"], stock_code=r["stock_code"], corp_name=r["corp_name"],
                occurred_at=r["published_at"], title=r["title"] or "",
                url=r["url"], source_type=r["source_type"], signal_type=None))

    if follows_rows:
        fph = ",".join("?" for _ in follows_rows)
        for r in conn.execute(f"""
            SELECT DISTINCT rd.id doc_id, e.id entity_id, e.type entity_type, e.name,
                   e.aliases, rd.published_at, rd.title, rd.url, rd.source_type
            FROM entity_links el
            JOIN entities e ON el.entity_id = e.id
            JOIN raw_documents rd ON el.doc_id = rd.id
            WHERE el.entity_id IN ({fph}) AND rd.published_at >= ?
            ORDER BY rd.published_at DESC LIMIT 50
        """, [*[f["id"] for f in follows_rows], since_dt]):
            if r["doc_id"] in seen_docs:
                continue  # 왓치리스트 종목으로 이미 포함된 문서는 중복 제거
            seen_docs.add(r["doc_id"])
            updates.append(WatchlistUpdate(
                kind="document", doc_id=r["doc_id"], entity_type=r["entity_type"], entity_id=r["entity_id"],
                stock_code=r["aliases"], corp_name=r["name"],
                occurred_at=r["published_at"], title=r["title"] or "",
                url=r["url"], source_type=r["source_type"], signal_type=None))

    if wl_codes:
        ph = ",".join("?" for _ in wl_codes)
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
        briefing=briefing[:3],
        calendar=calendar,
        follows=follows,
        watchlist_updates=updates[:30],
        market_highlights=highlights,
        watchlist_empty=not wl_codes and not follows,
        as_of=datetime.now(timezone.utc).isoformat(),
    )
