"""구독 소스 등록 — 텔레그램 채널 / 블로그.

- 등록 시 즉시 검증 (실제 스크랩 시도) → 실패하면 저장하지 않음
- 성공 시 저장 + 백그라운드로 첫 수집 실행 (enrich 포함 — 응답은 즉시 반환)
"""
import re

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/sources", tags=["spine"])


class AddTelegramRequest(BaseModel):
    channel: str   # 'cahier_de_market' | '@name' | 'https://t.me/name' 모두 허용


class AddBlogRequest(BaseModel):
    url: str


def _ingest_telegram(channel: str):
    from pipeline.connectors.telegram import TelegramConnector
    from pipeline.runner import run_source
    try:
        run_source(TelegramConnector([channel]))
    except Exception:
        pass


def _ingest_blog(url: str):
    from pipeline.connectors.blog import BlogConnector
    from pipeline.runner import run_source
    try:
        run_source(BlogConnector([url]))
    except Exception:
        pass


@router.post("/telegram", status_code=201)
def add_telegram(body: AddTelegramRequest, background: BackgroundTasks):
    ch = body.channel.strip()
    ch = re.sub(r"^https?://t\.me/(s/)?", "", ch).lstrip("@").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_]{3,64}", ch):
        raise HTTPException(400, "채널명 형식이 올바르지 않습니다 (예: cahier_de_market)")

    from services.telegram_service import get_channel_display_name, scrape_channel
    messages = scrape_channel(ch)
    if not messages:
        raise HTTPException(422, "공개 프리뷰를 읽을 수 없는 채널입니다 (비공개이거나 프리뷰 비활성)")
    display_name = get_channel_display_name(ch)

    conn = get_connection()
    dup = conn.execute("SELECT 1 FROM telegram_channels WHERE channel_name=?", (ch,)).fetchone()
    if not dup:
        conn.execute(
            "INSERT INTO telegram_channels (channel_name, display_name, is_active) VALUES (?, ?, 1)",
            (ch, display_name))
        conn.commit()
    conn.close()
    if dup:
        raise HTTPException(409, "이미 등록된 채널입니다")

    background.add_task(_ingest_telegram, ch)
    return {"channel": ch, "preview_messages": len(messages), "note": "백그라운드 수집 시작"}


@router.post("/blog", status_code=201)
def add_blog(body: AddBlogRequest, background: BackgroundTasks):
    url = body.url.strip().rstrip("/")
    if not url.startswith("http"):
        url = f"https://{url}"
    # 네이버 모바일 URL 정규화 — 포스트 URL(blog.naver.com)과 프리픽스 매칭돼야
    # 채널명 표시·소스 건강 집계가 정확해진다
    url = url.replace("://m.blog.naver.com/", "://blog.naver.com/")

    from services.blog_service import detect_platform_and_feed_url, fetch_blog_author, verify_and_fetch
    platform, feed_url = detect_platform_and_feed_url(url)
    try:
        posts, blog_name = verify_and_fetch(feed_url)
    except Exception as e:
        raise HTTPException(422, f"RSS 피드를 읽을 수 없습니다: {e}")

    author = fetch_blog_author(url, posts)

    conn = get_connection()
    dup = conn.execute("SELECT 1 FROM blog_sources WHERE url=?", (url,)).fetchone()
    if not dup:
        conn.execute(
            "INSERT INTO blog_sources (url, platform, blog_name, author, is_active) VALUES (?, ?, ?, ?, 1)",
            (url, platform, blog_name, author))
        conn.commit()
    conn.close()
    if dup:
        raise HTTPException(409, "이미 등록된 블로그입니다")

    background.add_task(_ingest_blog, url)
    return {"url": url, "blog_name": blog_name, "author": author, "platform": platform,
            "preview_posts": len(posts), "note": "백그라운드 수집 시작"}


class AddYouTubeRequest(BaseModel):
    input: str   # 채널 URL/@handle (구독) 또는 영상 URL/ID (단건)


def _ingest_youtube(video_ids: list[str] | None):
    from pipeline.connectors.youtube import YouTubeConnector
    from pipeline.runner import run_source
    try:
        run_source(YouTubeConnector(video_ids))
    except Exception:
        pass


@router.post("/youtube", status_code=201)
def add_youtube(body: AddYouTubeRequest, background: BackgroundTasks):
    from pipeline.connectors.youtube import parse_video_id, resolve_channel_id, fetch_transcript
    s = body.input.strip()

    # 1) 영상 링크/ID면 단건 수집 (watch·youtu.be·live·shorts만 — 채널 URL 오인 방지)
    vid = parse_video_id(s) if ("watch" in s or "youtu.be" in s or "/live/" in s
                                or "/shorts/" in s or len(s) == 11) else None
    if vid:
        if not fetch_transcript(vid):
            raise HTTPException(422, "이 영상은 자막(transcript)이 없어 수집할 수 없습니다")
        background.add_task(_ingest_youtube, [vid])
        return {"kind": "video", "video_id": vid, "note": "자막 수집 시작"}

    # 2) 채널 구독 — 이후 신규 영상 자동 수집
    resolved = resolve_channel_id(s)
    if not resolved:
        raise HTTPException(422, "채널을 찾을 수 없습니다 (채널 URL 또는 @handle을 입력하세요)")
    cid, title = resolved
    conn = get_connection()
    dup = conn.execute("SELECT 1 FROM youtube_channels WHERE channel_id=?", (cid,)).fetchone()
    if not dup:
        conn.execute(
            "INSERT INTO youtube_channels (channel_id, handle, title, is_active) VALUES (?, ?, ?, 1)",
            (cid, s if s.startswith("@") else None, title))
        conn.commit()
    conn.close()
    if dup:
        raise HTTPException(409, "이미 구독 중인 채널입니다")
    background.add_task(_ingest_youtube, None)
    return {"kind": "channel", "channel_id": cid, "title": title, "note": "구독 완료 — 최근 영상 자막 수집 시작"}


@router.get("/youtube")
def list_youtube():
    conn = get_connection()
    rows = conn.execute(
        "SELECT channel_id, title, handle, is_active FROM youtube_channels ORDER BY added_at DESC").fetchall()
    conn.close()
    return {"items": [{"channel_id": r["channel_id"], "title": r["title"],
                       "handle": r["handle"], "is_active": bool(r["is_active"])} for r in rows]}


@router.patch("/youtube/{channel_id}")
def toggle_youtube(channel_id: str, is_active: bool):
    conn = get_connection()
    conn.execute("UPDATE youtube_channels SET is_active=? WHERE channel_id=?",
                 (int(is_active), channel_id))
    conn.commit()
    conn.close()
    return {"channel_id": channel_id, "is_active": is_active}


class SourceHealth(BaseModel):
    kind: str            # telegram | blog | youtube
    name: str            # 표시명
    key: str             # channel_name | url | channel_id
    is_active: bool      # 개인 노출(뮤트) 축
    collect_enabled: bool = True   # 수집 축 (D-126) — 둘은 독립
    last_doc_at: str | None
    docs_7d: int
    docs_24h: int
    warning: bool        # 수집 켜진 활성 소스인데 7일간 유입 0
    # 소비 지표 30일 (D-127) — 수집량 대비 실제로 쓰였나
    docs_30d: int = 0
    untagged_30d: int = 0        # enrich가 태깅 못 한 문서 (온톨로지 기여 0)
    stock_linked_30d: int = 0    # 종목이 연결된 문서
    causal_30d: int = 0          # 인과 엣지로 기여한 문서 (가장 강한 소비 신호)
    last_fetch_at: str | None = None   # raw_documents.fetched_at 최대 (레지스트리 컬럼은 죽어 있음)
    shared_domain: bool = False  # 같은 도메인 피드가 여럿 — 숫자가 서로 중복 집계됨


class SourcesHealthResponse(BaseModel):
    items: list[SourceHealth]
    warnings: int
    as_of: str


# 소비 지표 — 수집량 대비 '실제로 쓰였나' (D-127). 30일 창.
_CONSUME_SQL = """
    SELECT COUNT(*) n,
      SUM(CASE WHEN (SELECT COUNT(*) FROM entity_links el WHERE el.doc_id=rd.id)=0
               THEN 1 ELSE 0 END) untagged,
      SUM(CASE WHEN EXISTS (SELECT 1 FROM entity_links el2
                            WHERE el2.doc_id=rd.id AND el2.link_type='stock')
               THEN 1 ELSE 0 END) stock_linked,
      SUM(CASE WHEN EXISTS (SELECT 1 FROM entity_relations er WHERE er.source_doc_id=rd.id)
               THEN 1 ELSE 0 END) causal,
      MAX(rd.fetched_at) last_fetch
    FROM raw_documents rd
    WHERE rd.source_type=? AND rd.published_at >= datetime('now','-30 days') AND {cond}
"""


def _consume(conn, source_type: str, cond: str, arg) -> dict:
    r = conn.execute(_CONSUME_SQL.format(cond=cond), (source_type, arg)).fetchone()
    n = r["n"] or 0
    return {"docs_30d": n, "untagged_30d": r["untagged"] or 0,
            "stock_linked_30d": r["stock_linked"] or 0, "causal_30d": r["causal"] or 0,
            "last_fetch_at": r["last_fetch"]}


def compute_source_health(conn) -> list[dict]:
    """소스별 유입 + **소비** 상태 — '조용한 날'이 시장 탓인지 수집 고장 탓인지, 그리고
    들어온 문서가 실제로 쓰이는지(태깅·종목연결·인과기여)까지 한 표에서 본다 (D-127).

    주의: `last_fetched_at`(레지스트리 컬럼)은 **어디서도 갱신되지 않는 죽은 컬럼**이라 쓰지 않고,
    `raw_documents.fetched_at`의 최대값을 실제 수집 시각으로 쓴다.
    """
    items = []
    for r in conn.execute("SELECT channel_name, display_name, is_active, "
                          "COALESCE(collect_enabled,1) ce FROM telegram_channels"):
        st = conn.execute("""
            SELECT max(published_at) last, 
                   sum(published_at >= datetime('now', '-7 days')) d7,
                   sum(published_at >= datetime('now', '-1 day')) d1
            FROM raw_documents WHERE source_type='telegram' AND source_id LIKE ? || '/%'
        """, (r["channel_name"],)).fetchone()
        d7 = st["d7"] or 0
        items.append({
            "kind": "telegram", "name": r["display_name"] or r["channel_name"],
            "key": r["channel_name"], "is_active": bool(r["is_active"]),
            "collect_enabled": bool(r["ce"]),
            "last_doc_at": st["last"], "docs_7d": d7, "docs_24h": st["d1"] or 0,
            # 수집을 끈 소스는 유입 0이 정상이므로 경고 대상이 아니다
            "warning": bool(r["is_active"]) and bool(r["ce"]) and d7 == 0,
            "shared_domain": False,
            **_consume(conn, "telegram", "rd.source_id LIKE ? || '/%'", r["channel_name"]),
        })
    from pipeline.urls import is_feedlike, norm_domain
    # 같은 도메인을 공유하는 피드가 여러 개면 도메인 매칭이 서로의 문서를 중복 집계한다
    # (실측: mk.co.kr 3피드가 모두 같은 기사에 매칭 → '경제'에 전부 귀속돼 나머지가 0건으로 보였다).
    # 숫자를 고칠 수는 없으니 **그 사실을 플래그로 드러낸다**(조용한 오해 금지).
    from collections import Counter
    from pipeline.urls import is_feedlike as _fl, norm_domain as _nd
    _dom_count = Counter(_nd(x["url"]) for x in
                         conn.execute("SELECT url FROM blog_sources").fetchall() if _fl(x["url"]))
    for r in conn.execute("SELECT url, blog_name, author, is_active, "
                          "COALESCE(collect_enabled,1) ce FROM blog_sources"):
        # RSS 직등록 소스(뉴스·뉴스레터)는 기사 url이 피드 url로 시작하지 않음 → 도메인 매칭
        if is_feedlike(r["url"]):
            cond, arg = "url LIKE '%//%' || ? || '%'", norm_domain(r["url"])
        else:
            cond, arg = "url LIKE ? || '%'", r["url"]
        st = conn.execute(f"""
            SELECT max(published_at) last,
                   sum(published_at >= datetime('now', '-7 days')) d7,
                   sum(published_at >= datetime('now', '-1 day')) d1
            FROM raw_documents WHERE source_type='blog' AND {cond}
        """, (arg,)).fetchone()
        d7 = st["d7"] or 0
        shared = _fl(r["url"]) and _dom_count.get(norm_domain(r["url"]), 0) > 1
        items.append({
            "kind": "blog", "name": r["blog_name"] or r["url"],
            "key": r["url"], "is_active": bool(r["is_active"]),
            "collect_enabled": bool(r["ce"]),
            "last_doc_at": st["last"], "docs_7d": d7, "docs_24h": st["d1"] or 0,
            "warning": bool(r["is_active"]) and bool(r["ce"]) and d7 == 0 and not shared,
            "shared_domain": bool(shared),
            **_consume(conn, "blog", cond.replace("url", "rd.url"), arg),
        })
    # 유튜브도 같은 표에 (전엔 빠져 있어 15개 채널이 계기판에서 안 보였다, D-127)
    for r in conn.execute("SELECT channel_id, handle, title, is_active, "
                          "COALESCE(collect_enabled,1) ce FROM youtube_channels"):
        st = conn.execute("""
            SELECT max(published_at) last,
                   sum(published_at >= datetime('now', '-7 days')) d7,
                   sum(published_at >= datetime('now', '-1 day')) d1
            FROM raw_documents WHERE source_type='youtube' AND source_id LIKE ? || '/%'
        """, (r["channel_id"],)).fetchone()
        d7 = st["d7"] or 0
        items.append({
            "kind": "youtube", "name": r["title"] or r["handle"] or r["channel_id"],
            "key": r["channel_id"], "is_active": bool(r["is_active"]),
            "collect_enabled": bool(r["ce"]),
            "last_doc_at": st["last"], "docs_7d": d7, "docs_24h": st["d1"] or 0,
            "warning": bool(r["is_active"]) and bool(r["ce"]) and d7 == 0,
            "shared_domain": False,
            **_consume(conn, "youtube", "rd.source_id LIKE ? || '/%'", r["channel_id"]),
        })
    return items


class DossierEntity(BaseModel):
    entity_id: int
    name: str
    link_type: str       # stock | industry | topic
    aliases: str | None  # 종목이면 종목코드
    count: int


class DossierDoc(BaseModel):
    id: int
    title: str
    published_at: str | None


class DossierSummary(BaseModel):
    status: str          # fresh | cached | empty | unavailable | failed
    digest: str | None
    insights: str | None
    created_at: str | None
    doc_count: int


class SourceDossierResponse(BaseModel):
    kind: str
    key: str
    name: str
    author: str | None
    is_active: bool
    total_docs: int
    first_doc_at: str | None
    last_doc_at: str | None
    docs_7d: int
    summary: DossierSummary | None   # 캐시만 (LLM 호출 없음)
    summary_stale: bool              # true면 프론트가 POST /dossier/summary 호출
    top_entities: list[DossierEntity]
    recent_docs: list[DossierDoc]


@router.get("/dossier", response_model=SourceDossierResponse)
def source_dossier(kind: str, key: str):
    """소스 도시에 — LLM 호출 없이 즉시 응답. 요약은 캐시 + stale 플래그만."""
    from pipeline.source_dossier import (_doc_filter, get_cached, profile_hash,
                                         recent_docs, resolve_source, PROFILE_DOCS)
    conn = get_connection()
    src = resolve_source(conn, kind, key)
    if not src:
        conn.close()
        raise HTTPException(404, "등록되지 않은 소스입니다")

    df, arg = _doc_filter(kind, key)
    st = conn.execute(f"""
        SELECT count(*) n, min(published_at) first, max(published_at) last,
               sum(published_at >= datetime('now', '-7 days')) d7
        FROM raw_documents WHERE {df}""", (arg,)).fetchone()

    docs = recent_docs(conn, kind, key, PROFILE_DOCS)
    cached = get_cached(conn, kind, key)
    stale = bool(docs) and (not cached or cached["doc_ids_hash"] != profile_hash(docs))
    summary = DossierSummary(
        status="cached", digest=cached["digest"], insights=cached["insights"],
        created_at=cached["created_at"], doc_count=cached["doc_count"] or 0) if cached else None

    top = conn.execute(f"""
        SELECT e.id entity_id, e.name, el.link_type, e.aliases, count(*) c
        FROM raw_documents rd
        JOIN entity_links el ON el.doc_id = rd.id
        JOIN entities e ON el.entity_id = e.id
        WHERE {df} AND rd.published_at >= datetime('now', '-90 days')
          AND el.link_type IN ('stock', 'industry', 'topic')
        GROUP BY e.id, el.link_type ORDER BY c DESC LIMIT 12
    """, (arg,)).fetchall()

    recent = conn.execute(f"""
        SELECT id, title, published_at FROM raw_documents WHERE {df}
        ORDER BY published_at DESC LIMIT 20""", (arg,)).fetchall()
    conn.close()

    return SourceDossierResponse(
        kind=src["kind"], key=src["key"], name=src["name"], author=src["author"],
        is_active=src["is_active"], total_docs=st["n"] or 0,
        first_doc_at=st["first"], last_doc_at=st["last"], docs_7d=st["d7"] or 0,
        summary=summary, summary_stale=stale,
        top_entities=[DossierEntity(entity_id=r["entity_id"], name=r["name"],
                                    link_type=r["link_type"], aliases=r["aliases"], count=r["c"])
                      for r in top],
        recent_docs=[DossierDoc(id=r["id"], title=r["title"] or "(제목 없음)",
                                published_at=r["published_at"]) for r in recent],
    )


@router.post("/dossier/summary", response_model=DossierSummary)
def source_dossier_summary(kind: str, key: str):
    """관점 프로필 생성 — 새 글이 있을 때만 LLM 호출 (아니면 캐시 반환)."""
    from pipeline.source_dossier import compute_profile
    r = compute_profile(kind, key)
    if r.get("status") == "not_found":
        raise HTTPException(404, "등록되지 않은 소스입니다")
    return DossierSummary(status=r["status"], digest=r.get("digest"),
                          insights=r.get("insights"), created_at=r.get("created_at"),
                          doc_count=r.get("doc_count") or 0)


class CollectToggle(BaseModel):
    kind: str            # telegram | blog | youtube
    key: str             # channel_name | url | channel_id
    enabled: bool


@router.post("/collect")
def set_collect(body: CollectToggle):
    """수집 축 토글 (D-126) — `is_active`(뮤트)와 **독립**이다.

    뮤트는 내 피드에서만 감추고 코퍼스는 계속 쌓는다(수집=공공재). 이 토글은 수집 자체를 끈다.
    """
    table, col = {
        "telegram": ("telegram_channels", "channel_name"),
        "blog": ("blog_sources", "url"),
        "youtube": ("youtube_channels", "channel_id"),
    }.get(body.kind, (None, None))
    if not table:
        raise HTTPException(400, "알 수 없는 kind")
    conn = get_connection()
    cur = conn.execute(f"UPDATE {table} SET collect_enabled=? WHERE {col}=?",
                       (1 if body.enabled else 0, body.key))
    conn.commit()
    conn.close()
    if not cur.rowcount:
        raise HTTPException(404, "해당 소스를 찾을 수 없습니다")
    return {"kind": body.kind, "key": body.key, "collect_enabled": body.enabled}


@router.get("/health", response_model=SourcesHealthResponse)
def sources_health():
    from datetime import datetime, timezone
    conn = get_connection()
    items = compute_source_health(conn)
    conn.close()
    return SourcesHealthResponse(
        items=[SourceHealth(**i) for i in items],
        warnings=sum(1 for i in items if i["warning"]),
        as_of=datetime.now(timezone.utc).isoformat(),
    )
