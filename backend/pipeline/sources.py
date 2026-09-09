"""문서 → 출처 이름 (D-143 단일화).

같은 판정이 두 곳에 필요하다: 피드 카드의 출처 표시(라우터)와 대화 도구가 근거에 실어 보낼
출처(chat_tools). 전엔 라우터에만 있어서, 대화 도구는 채널로 필터해 놓고도 "이게 누구 문서인지"를
종합 모델에게 알려주지 못했다(chatId=37 '태린이 아빠' 오답의 원인).

반환 {doc_id: {"name", "kind", "key"}} — kind/key는 소스 도시에(/source?kind=&key=) 링크용,
레지스트리 미등록이면 None.
"""


def source_names(conn, rows) -> dict[int, dict | None]:
    """rows는 id·source_type·source_id·url을 가진 행들(sqlite3.Row 또는 dict)."""
    tg = {r["channel_name"]: (r["display_name"] or r["channel_name"]) for r in
          conn.execute("SELECT channel_name, display_name FROM telegram_channels")}
    blogs = [(r["url"], r["blog_name"] or r["url"]) for r in
             conn.execute("SELECT url, blog_name FROM blog_sources ORDER BY length(url) DESC")]
    yt = {r["channel_id"]: r["title"] for r in
          conn.execute("SELECT channel_id, title FROM youtube_channels")}

    def get(r, key):
        try:
            return r[key]
        except (KeyError, IndexError):
            return None

    ids = [get(r, "id") for r in rows]
    scrap_origin: dict[int, str] = {}
    if ids:
        ph = ",".join("?" for _ in ids)
        scrap_origin = {r["doc_id"]: r["channel"] for r in conn.execute(
            f"SELECT doc_id, channel FROM scrap_links WHERE doc_id IN ({ph})", ids) if r["channel"]}

    out: dict[int, dict | None] = {}
    for r in rows:
        did, st = get(r, "id"), get(r, "source_type")
        sid, url = get(r, "source_id") or "", get(r, "url") or ""
        if st == "telegram":
            ch = sid.split("/")[0]
            out[did] = {"name": tg.get(ch, ch), "kind": "telegram" if ch in tg else None,
                        "key": ch if ch in tg else None} if ch else None
        elif st == "blog":
            from pipeline.urls import url_belongs
            hit = next(((p, n) for p, n in blogs if url.startswith(p)), None)
            if not hit:  # RSS 직등록 소스(뉴스·뉴스레터) — 도메인 fallback
                hit = next(((p, n) for p, n in blogs if url_belongs(url, p)), None)
            out[did] = {"name": hit[1], "kind": "blog", "key": hit[0]} if hit else None
        elif st == "youtube":
            cid = sid.split("/")[0] if "/" in sid else None
            out[did] = {"name": yt.get(cid), "kind": "youtube", "key": cid} \
                if cid and cid in yt else {"name": "YouTube", "kind": None, "key": None}
        elif st == "scrap":
            # 스크랩 — 원본은 '스크랩한 채널'. 블로거 이름은 제목에 이미 붙어 있다 (D-142)
            ch = scrap_origin.get(did)
            out[did] = {"name": (tg.get(ch, ch) if ch else "스크랩"),
                        "kind": "telegram" if ch in tg else None, "key": ch if ch in tg else None}
        elif st == "note":
            out[did] = {"name": "내 노트", "kind": None, "key": None}
        else:
            out[did] = None
    return out
