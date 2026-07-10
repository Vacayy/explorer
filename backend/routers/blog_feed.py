from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from database import get_connection
from services.blog_service import detect_platform_and_feed_url, verify_and_fetch, scrape_rss
from services.tagging_service import auto_tag_post, get_tags_for_posts, get_all_tags

router = APIRouter(prefix="/api/blog", tags=["blog"])

CACHE_TTL_MINUTES = 60


class AddSourceRequest(BaseModel):
    url: str


class ToggleSourceRequest(BaseModel):
    is_active: bool


def _is_cache_fresh(last_fetched: str | None) -> bool:
    if not last_fetched:
        return False
    try:
        dt = datetime.fromisoformat(last_fetched)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - dt < timedelta(minutes=CACHE_TTL_MINUTES)
    except Exception:
        return False


# ── Sources CRUD ─────────────────────────────────────────────────

@router.get("/sources")
def list_sources():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, url, platform, blog_name, author, is_active, last_fetched_at, added_at FROM blog_sources ORDER BY added_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/sources", status_code=201)
def add_source(body: AddSourceRequest):
    url = body.url.strip().rstrip("/")
    if not url:
        raise HTTPException(400, "유효한 블로그 URL을 입력해주세요")

    conn = get_connection()
    existing = conn.execute(
        "SELECT id, is_active FROM blog_sources WHERE url = ?", (url,)
    ).fetchone()
    if existing:
        if not existing["is_active"]:
            conn.execute("UPDATE blog_sources SET is_active = 1 WHERE id = ?", (existing["id"],))
            conn.commit()
        row = conn.execute(
            "SELECT id, url, platform, blog_name, is_active, last_fetched_at, added_at FROM blog_sources WHERE id = ?",
            (existing["id"],),
        ).fetchone()
        conn.close()
        return dict(row)
    conn.close()

    try:
        platform, feed_url = detect_platform_and_feed_url(url)
        posts, blog_name = verify_and_fetch(feed_url)
    except Exception as e:
        raise HTTPException(422, f"블로그를 가져올 수 없습니다: {e}")

    conn = get_connection()
    conn.execute(
        "INSERT INTO blog_sources (url, platform, blog_name, is_active) VALUES (?, ?, ?, 1)",
        (url, platform, blog_name or url),
    )
    conn.commit()
    source_row = conn.execute(
        "SELECT id, url, platform, blog_name, is_active, last_fetched_at, added_at FROM blog_sources WHERE url = ?",
        (url,),
    ).fetchone()
    source_id = source_row["id"]

    # Persist initial posts
    new_post_ids: list[tuple[int, str, str]] = []
    for p in posts:
        if not p.get("url"):
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO blog_posts
               (source_id, title, summary, content, author, url, published_at, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (source_id, p["title"], p["summary"], p["content"], p.get("author", ""), p["url"], p["published_at"]),
        )
        if cur.lastrowid:
            new_post_ids.append((cur.lastrowid, p["title"], p.get("summary") or ""))
    conn.execute(
        "UPDATE blog_sources SET last_fetched_at = datetime('now') WHERE id = ?", (source_id,)
    )
    conn.commit()
    for pid, title, summary in new_post_ids:
        auto_tag_post(pid, title, summary)
    row = conn.execute(
        "SELECT id, url, platform, blog_name, is_active, last_fetched_at, added_at FROM blog_sources WHERE id = ?",
        (source_id,),
    ).fetchone()
    conn.close()
    return dict(row)


@router.put("/sources/{source_id}/toggle")
def toggle_source(source_id: int, body: ToggleSourceRequest):
    conn = get_connection()
    existing = conn.execute("SELECT id FROM blog_sources WHERE id = ?", (source_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "블로그 소스를 찾을 수 없습니다")
    conn.execute(
        "UPDATE blog_sources SET is_active = ? WHERE id = ?",
        (1 if body.is_active else 0, source_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, url, platform, blog_name, is_active, last_fetched_at, added_at FROM blog_sources WHERE id = ?",
        (source_id,),
    ).fetchone()
    conn.close()
    return dict(row)


# ── Feed ─────────────────────────────────────────────────────────

def _fetch_and_cache_source(source_id: int, url: str) -> None:
    try:
        _, feed_url = detect_platform_and_feed_url(url)
        posts, blog_name = scrape_rss(feed_url)
    except Exception:
        return

    conn = get_connection()
    new_post_ids: list[tuple[int, str, str]] = []
    for p in posts:
        if not p.get("url"):
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO blog_posts
               (source_id, title, summary, content, author, url, published_at, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (source_id, p["title"], p["summary"], p["content"], p.get("author", ""), p["url"], p["published_at"]),
        )
        if cur.lastrowid:
            new_post_ids.append((cur.lastrowid, p["title"], p.get("summary") or ""))
    if blog_name:
        conn.execute("UPDATE blog_sources SET blog_name = ? WHERE id = ?", (blog_name, source_id))
    conn.execute(
        "UPDATE blog_sources SET last_fetched_at = datetime('now') WHERE id = ?", (source_id,)
    )
    conn.commit()
    conn.close()
    for pid, title, summary in new_post_ids:
        auto_tag_post(pid, title, summary)


@router.get("/tags")
def list_tags():
    return get_all_tags()


@router.get("/feed")
def get_feed(tag: Optional[str] = Query(None)):
    conn = get_connection()
    sources = conn.execute(
        "SELECT id, url, last_fetched_at FROM blog_sources WHERE is_active = 1"
    ).fetchall()
    conn.close()

    for src in sources:
        if not _is_cache_fresh(src["last_fetched_at"]):
            _fetch_and_cache_source(src["id"], src["url"])

    conn = get_connection()
    if tag:
        rows = conn.execute(
            """SELECT bp.id, bp.source_id, bp.title, bp.summary, bp.author, bp.url, bp.published_at, bp.fetched_at,
                      bs.blog_name, bs.platform
               FROM blog_posts bp
               JOIN blog_sources bs ON bs.id = bp.source_id
               JOIN blog_post_tags bpt ON bpt.post_id = bp.id
               WHERE bs.is_active = 1 AND bpt.tag_value = ?
               ORDER BY COALESCE(bp.published_at, bp.fetched_at) DESC
               LIMIT 200""",
            (tag,)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT bp.id, bp.source_id, bp.title, bp.summary, bp.author, bp.url, bp.published_at, bp.fetched_at,
                      bs.blog_name, bs.platform
               FROM blog_posts bp
               JOIN blog_sources bs ON bs.id = bp.source_id
               WHERE bs.is_active = 1
               ORDER BY COALESCE(bp.published_at, bp.fetched_at) DESC
               LIMIT 200"""
        ).fetchall()
    conn.close()

    items = [dict(r) for r in rows]
    post_ids = [item["id"] for item in items]
    tags_by_post = get_tags_for_posts(post_ids)
    for item in items:
        item["tags"] = tags_by_post.get(item["id"], [])

    return {"items": items, "total": len(items)}


@router.get("/posts/{post_id}")
def get_post(post_id: int):
    conn = get_connection()
    row = conn.execute(
        """SELECT bp.id, bp.source_id, bp.title, bp.summary, bp.content, bp.author, bp.url,
                  bp.published_at, bp.fetched_at, bs.blog_name, bs.platform
           FROM blog_posts bp
           JOIN blog_sources bs ON bs.id = bp.source_id
           WHERE bp.id = ?""",
        (post_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "포스트를 찾을 수 없습니다")

    result = dict(row)

    # If content is short (RSS truncated), try fetching full article
    content = result.get("content") or ""
    if len(content) < 1500 and result.get("url"):
        from services.blog_service import fetch_full_content
        full = fetch_full_content(result["url"])
        if full and len(full) > len(content):
            result["content"] = full
            # Cache the full content in DB
            conn.execute(
                "UPDATE blog_posts SET content = ? WHERE id = ?",
                (full, post_id),
            )
            conn.commit()

    conn.close()
    return result
