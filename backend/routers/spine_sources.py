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

    from services.telegram_service import scrape_channel
    messages = scrape_channel(ch)
    if not messages:
        raise HTTPException(422, "공개 프리뷰를 읽을 수 없는 채널입니다 (비공개이거나 프리뷰 비활성)")

    conn = get_connection()
    dup = conn.execute("SELECT 1 FROM telegram_channels WHERE channel_name=?", (ch,)).fetchone()
    if not dup:
        conn.execute("INSERT INTO telegram_channels (channel_name, is_active) VALUES (?, 1)", (ch,))
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

    from services.blog_service import detect_platform_and_feed_url, verify_and_fetch
    platform, feed_url = detect_platform_and_feed_url(url)
    try:
        posts, blog_name = verify_and_fetch(feed_url)
    except Exception as e:
        raise HTTPException(422, f"RSS 피드를 읽을 수 없습니다: {e}")

    conn = get_connection()
    dup = conn.execute("SELECT 1 FROM blog_sources WHERE url=?", (url,)).fetchone()
    if not dup:
        conn.execute(
            "INSERT INTO blog_sources (url, platform, blog_name, is_active) VALUES (?, ?, ?, 1)",
            (url, platform, blog_name))
        conn.commit()
    conn.close()
    if dup:
        raise HTTPException(409, "이미 등록된 블로그입니다")

    background.add_task(_ingest_blog, url)
    return {"url": url, "blog_name": blog_name, "platform": platform,
            "preview_posts": len(posts), "note": "백그라운드 수집 시작"}
