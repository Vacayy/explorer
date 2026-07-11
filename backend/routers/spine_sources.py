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


class SourceHealth(BaseModel):
    kind: str            # telegram | blog
    name: str            # 표시명
    key: str             # channel_name | url
    is_active: bool
    last_doc_at: str | None
    docs_7d: int
    docs_24h: int
    warning: bool        # 활성인데 7일간 유입 0


class SourcesHealthResponse(BaseModel):
    items: list[SourceHealth]
    warnings: int
    as_of: str


def compute_source_health(conn) -> list[dict]:
    """소스별 유입 상태 — '조용한 날'이 시장 탓인지 수집 고장 탓인지 구분하는 계기판."""
    items = []
    for r in conn.execute("SELECT channel_name, display_name, is_active FROM telegram_channels"):
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
            "last_doc_at": st["last"], "docs_7d": d7, "docs_24h": st["d1"] or 0,
            "warning": bool(r["is_active"]) and d7 == 0,
        })
    for r in conn.execute("SELECT url, blog_name, author, is_active FROM blog_sources"):
        st = conn.execute("""
            SELECT max(published_at) last,
                   sum(published_at >= datetime('now', '-7 days')) d7,
                   sum(published_at >= datetime('now', '-1 day')) d1
            FROM raw_documents WHERE source_type='blog' AND url LIKE ? || '%'
        """, (r["url"],)).fetchone()
        d7 = st["d7"] or 0
        items.append({
            "kind": "blog", "name": r["blog_name"] or r["url"],
            "key": r["url"], "is_active": bool(r["is_active"]),
            "last_doc_at": st["last"], "docs_7d": d7, "docs_24h": st["d1"] or 0,
            "warning": bool(r["is_active"]) and d7 == 0,
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

    df = _doc_filter(kind)
    st = conn.execute(f"""
        SELECT count(*) n, min(published_at) first, max(published_at) last,
               sum(published_at >= datetime('now', '-7 days')) d7
        FROM raw_documents WHERE {df}""", (key,)).fetchone()

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
    """, (key,)).fetchall()

    recent = conn.execute(f"""
        SELECT id, title, published_at FROM raw_documents WHERE {df}
        ORDER BY published_at DESC LIMIT 20""", (key,)).fetchall()
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
