"""Read-only projection of existing publications; no LLM, backfill or new event store."""
import json
from datetime import datetime, timezone
from urllib.parse import quote

from models.spine import EntityTag, FeedDocument
from models.timeline import TimelineItem, TimelineLink, TimelineResponse, TimelineChannel, TimelineChannelsResponse
from pipeline.sources import source_names
from pipeline.urls import url_belongs


def utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _company_link(name: str, code: str | None) -> str:
    if code and code.isdigit() and len(code) == 6:
        return f"/analyze/{code}/summary"
    if code:
        return f"/us/{quote(code, safe='')}"
    return f"/feed?view=documents&q={quote(name, safe='')}"


def _documents(conn, ids: list[int]) -> dict[int, FeedDocument]:
    if not ids:
        return {}
    ph = ",".join("?" for _ in ids)
    rows = conn.execute(f"""
        SELECT rd.*, en.summary, en.model enrich_model FROM raw_documents rd
        LEFT JOIN enrichments en ON en.doc_id=rd.id WHERE rd.id IN ({ph})
    """, ids).fetchall()
    tags = {i: [] for i in ids}
    for r in conn.execute(f"""
        SELECT el.doc_id, el.entity_id, e.type, e.name, e.aliases, el.link_type, el.confidence
        FROM entity_links el JOIN entities e ON e.id=el.entity_id WHERE el.doc_id IN ({ph})
    """, ids):
        tags[r["doc_id"]].append(EntityTag(**{k: r[k] for k in r.keys() if k != "doc_id"}))
    names = source_names(conn, rows)
    out = {}
    for r in rows:
        name = names.get(r["id"]) or {}
        try:
            images = json.loads(r["media_json"] or "[]")
            images = [i for i in images if isinstance(i, str)] if isinstance(images, list) else []
        except (ValueError, TypeError):
            images = []
        out[r["id"]] = FeedDocument(
            id=r["id"], source_type=r["source_type"], title=r["title"] or "",
            url=r["url"] or "", published_at=utc(r["published_at"] or r["fetched_at"]),
            summary=r["summary"], content=r["markdown"], images=images,
            channel=name.get("name"), channel_kind=name.get("kind"), channel_key=name.get("key"),
            enrich_model=r["enrich_model"], entities=tags[r["id"]],
        )
    return out


def _projection(conn, scope="all", source="all"):
    blogs = list(conn.execute("SELECT url, blog_name FROM blog_sources ORDER BY length(url) DESC"))
    def blog_key(url):
        for prefix_only in (True, False):
            for row in blogs:
                if url_belongs(url or "", row["url"], prefix_only=prefix_only):
                    return row["url"]
        return ""
    conn.create_function("feed_blog_key", 1, blog_key)
    conn.create_function("feed_url_belongs", 2, lambda u, p: int(url_belongs(u or "", p or "")))
    # Only active subscriptions enter the source lane, including YouTube mute state.
    source_sql = """
        SELECT 'source:' || rd.id id, 'source' kind, rd.id ref,
               COALESCE(NULLIF(rd.published_at,''),rd.fetched_at) ts,
               rd.source_type || ':' || CASE WHEN rd.source_type='blog' THEN feed_blog_key(rd.url)
                 ELSE substr(rd.source_id,1,instr(rd.source_id,'/')-1) END channel,
               rd.source_type platform, '' name,
               substr(COALESCE(NULLIF(rd.title,''),rd.markdown,''),1,180) preview
        FROM raw_documents rd WHERE
        (?='all' OR rd.source_type=?) AND (
          (rd.source_type='telegram' AND EXISTS (
            SELECT 1 FROM telegram_channels c WHERE c.is_active=1
            AND c.channel_name=substr(rd.source_id,1,instr(rd.source_id,'/')-1)))
          OR (rd.source_type='youtube' AND EXISTS (
            SELECT 1 FROM youtube_channels c WHERE c.is_active=1
            AND c.channel_id=substr(rd.source_id,1,instr(rd.source_id,'/')-1)))
          OR (rd.source_type='blog' AND EXISTS (
            SELECT 1 FROM blog_sources c WHERE c.is_active=1 AND feed_url_belongs(rd.url,c.url))
            AND NOT EXISTS (SELECT 1 FROM blog_sources c
              WHERE c.is_active=0 AND feed_url_belongs(rd.url,c.url)))
        )
    """
    system_sql = """
        SELECT 'company:' || d.id id, 'company' kind, d.id ref, d.created_at ts, 'company:' || e.id channel, 'system' platform, e.name name, substr(d.digest,1,180) preview
        FROM entity_digests d JOIN entities e ON e.id=d.entity_id
        WHERE e.type='company' AND trim(COALESCE(d.digest,''))!=''
        UNION ALL
        SELECT 'person:' || id, 'person', id, created_at, 'person:' || key, 'system', key, substr(digest,1,180) FROM source_digests
        WHERE kind='person' AND trim(COALESCE(digest,''))!=''
        UNION ALL
        SELECT 'transcript:' || t.id, 'transcript', t.id, t.fetched_at, 'transcript:' || t.ticker, 'system', COALESCE(f.company_name,t.ticker) || ' · 컨콜', substr(COALESCE(t.digest,'새 컨콜 원문'),1,180) FROM transcripts t
        JOIN transcript_follow f ON f.ticker=t.ticker AND f.active=1
        JOIN raw_documents rd ON rd.id=t.raw_doc_id
        UNION ALL
        SELECT 'trade:' || s.period, 'trade', s.period, MAX(s.fetched_at), 'trade:all', 'system', '관심 수출입 품목', s.period || ' 수출입 통계'
        FROM trade_stats s JOIN trade_follow f ON f.hs_code=s.hs_code AND f.active=1
        WHERE s.period=(SELECT MAX(s2.period) FROM trade_stats s2 WHERE s2.hs_code=s.hs_code)
        GROUP BY s.period
    """
    parts, params = [], []
    if scope in ("all", "sources"):
        parts.append(source_sql)
        params.extend([source, source])
    if scope in ("all", "system"):
        parts.append(system_sql)
    return " UNION ALL ".join(parts), params


def timeline(conn, *, scope="all", kind="all", source="all", channel=None, page=1, size=20, until=None):
    now = datetime.now(timezone.utc).isoformat()
    until = utc(until) if until else now
    sql, params = _projection(conn, scope, source)
    rows = conn.execute(f"""
        WITH updates AS ({sql}) SELECT * FROM updates
        WHERE julianday(ts)<=julianday(?) AND (?='all' OR kind=?) AND (? IS NULL OR channel=?)
        ORDER BY julianday(ts) DESC, id DESC LIMIT ? OFFSET ?
    """, [*params, until, kind, kind, channel, channel, size + 1, (page - 1) * size]).fetchall()
    has_more = len(rows) > size
    rows = rows[:size]
    docs = _documents(conn, [r["ref"] for r in rows if r["kind"] == "source"])
    items = []
    for row in rows:
        ref, item_kind = row["ref"], row["kind"]
        base = dict(id=row["id"], kind=item_kind, occurred_at=utc(row["ts"]))
        if item_kind == "source":
            doc = docs[ref]
            item = TimelineItem(**base, title=doc.title, subject=doc.channel or doc.source_type,
                                time_label="게시" if conn.execute("SELECT published_at FROM raw_documents WHERE id=?", (ref,)).fetchone()[0] else "수집",
                                to=f"/doc/{ref}", document=doc)
        elif item_kind == "company":
            r = conn.execute("SELECT d.*,e.name,e.aliases FROM entity_digests d JOIN entities e ON e.id=d.entity_id WHERE d.id=?", (ref,)).fetchone()
            label = {"1d": "하루", "1w": "주간", "7d": "7일", "1m": "월간"}.get(r["period"], r["period"])
            item = TimelineItem(**base, title=f"{r['name']} · {label} 요약", subject=r["name"],
                                body=r["digest"], period=f"{r['period_start']} · {label}",
                                time_label="요약 생성", evidence_count=r["doc_count"], ai_generated=True,
                                to=_company_link(r["name"], r["aliases"]))
        elif item_kind == "person":
            r = conn.execute("SELECT * FROM source_digests WHERE id=?", (ref,)).fetchone()
            item = TimelineItem(**base, title=f"{r['key']} · 인물 업데이트", subject=r["key"],
                                body=r["digest"], time_label="요약 생성", evidence_count=r["doc_count"],
                                ai_generated=True, to=f"/person?name={quote(r['key'], safe='')}")
        elif item_kind == "transcript":
            r = conn.execute("SELECT t.*,f.company_name FROM transcripts t JOIN transcript_follow f ON f.ticker=t.ticker WHERE t.id=?", (ref,)).fetchone()
            period = " ".join(str(v) for v in (r["fiscal_year"], r["fiscal_period"]) if v)
            item = TimelineItem(**base, title=f"{r['company_name']} · {period} 컨콜", subject=r["company_name"],
                                body=r["digest"] or "새 컨콜 원문이 수집됐습니다. 요약은 아직 없습니다.",
                                period=f"회계분기 {period}", time_label="수집", evidence_count=1,
                                ai_generated=bool(r["digest"]), to=f"/follow/transcripts?t={ref}",
                                links=[TimelineLink(label="컨콜 원문", to=f"/doc/{r['raw_doc_id']}")])
        else:
            stats = conn.execute("SELECT f.hs_code,f.item_name FROM trade_stats s JOIN trade_follow f ON f.hs_code=s.hs_code AND f.active=1 WHERE s.period=? AND s.period=(SELECT MAX(s2.period) FROM trade_stats s2 WHERE s2.hs_code=s.hs_code) ORDER BY f.group_label,f.hs_code", (ref,)).fetchall()
            names = " · ".join(r["item_name"] for r in stats[:3])
            item = TimelineItem(**base, title=f"{ref} 수출입 · {len(stats)}개 품목", subject="관심 수출입 품목",
                                body=f"{names}{' 등' if len(stats)>3 else ''}의 월별 통계를 확인할 수 있습니다. 수출·수입 추이와 전년 대비 변화를 비교하세요.",
                                period=f"통계 기준 {ref}", time_label="최근 수집", to="/follow/trade",
                                links=[TimelineLink(label=r["item_name"], to=f"/follow/trade?hs={quote(r['hs_code'])}") for r in stats[:3]])
        items.append(item)
    return TimelineResponse(items=items, page=page, size=size, has_more=has_more, until=until, as_of=now)


def channels(conn, *, until=None):
    """Aggregate the entire visible corpus, loading only each channel's latest excerpt."""
    until = utc(until) if until else datetime.now(timezone.utc).isoformat()
    sql, params = _projection(conn)
    rows = conn.execute(f"""
        WITH updates AS ({sql}), ranked AS (
          SELECT *, COUNT(*) OVER (PARTITION BY channel) count,
            ROW_NUMBER() OVER (PARTITION BY channel ORDER BY julianday(ts) DESC,id DESC) rank
          FROM updates WHERE julianday(ts)<=julianday(?)
        ) SELECT * FROM ranked WHERE rank=1
    """, [*params, until]).fetchall()
    registered = {}
    for table, key, name, platform in (
        ('telegram_channels','channel_name','display_name','telegram'),
        ('blog_sources','url','blog_name','blog'),
        ('youtube_channels','channel_id','title','youtube'),
    ):
        for r in conn.execute(f'SELECT {key} key,{name} name FROM {table} WHERE is_active=1'):
            ident = f'{platform}:{r["key"]}'
            registered[ident] = TimelineChannel(id=ident, name=r['name'] or r['key'], platform=platform)
    for r in rows:
        ident = r['channel']
        registered[ident] = TimelineChannel(
            id=ident, name=registered[ident].name if ident in registered else r['name'] or ident,
            platform=r['platform'], count=r['count'], latest_at=utc(r['ts']), preview=r['preview'] or '',
        )
    items = sorted(registered.values(), key=lambda i: (i.latest_at or '', i.id), reverse=True)
    return TimelineChannelsResponse(items=items, total=sum(i.count for i in items), until=until)
