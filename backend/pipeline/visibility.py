"""소스 뮤트(개인 노출 설정) — 수집은 공유 인프라, 노출은 사용자 설정.

is_active=0 = 뮤트: 내 피드·AI 답변에서 제외 (수집·다이제스트·신호 등
시스템 지능은 계속 축적 — 다시 켜면 그동안의 수집분이 그대로 보인다).
멀티유저 확장 시 이 모듈이 user_id별 뮤트 테이블로 바뀐다.
"""


# ── 미검증 소스 (D-142) ───────────────────────────────────────────────────────
# 내가 고르지 않은, 사실관계가 확인되지 않은 개인 주장. 지금은 링크 스크랩(scrap) 하나.
# **판정은 여기 한 곳에서만** — 네 경로(인과 추출·내러티브 생성·언급 급증·기본 검색)가 이 집합을 임포트한다.
# 규율(PHILOSOPHY §1 사실/가설 분리): 미검증 소스는 ①월드모델(엣지·내러티브) 입력에서 제외
# ②언급 급증 집계에서 제외 ③기본 검색 풀에서 제외(source를 명시할 때만 조회) ④읽히는 자리에는 라벨.
UNVERIFIED_SOURCES = {"scrap"}

_UNVERIFIED_SQL = ",".join(f"'{s}'" for s in sorted(UNVERIFIED_SOURCES))


def unverified_sql(col: str = "rd.source_type") -> str:
    """월드모델·신호 쿼리에 붙일 WHERE 조각 — 미검증 소스 제외. 파라미터 없음(상수 집합)."""
    return f"{col} NOT IN ({_UNVERIFIED_SQL})"


def is_unverified(source_type: str) -> bool:
    return source_type in UNVERIFIED_SOURCES


def get_muted(conn) -> dict:
    """뮤트된 소스 — {'telegram': set[채널명], 'blog': [url 프리픽스]}."""
    tg = {r["channel_name"] for r in conn.execute(
        "SELECT channel_name FROM telegram_channels WHERE is_active=0")}
    blogs = [r["url"] for r in conn.execute(
        "SELECT url FROM blog_sources WHERE is_active=0")]
    return {"telegram": tg, "blog": blogs}


def is_muted(source_type: str, source_id: str, url: str, muted: dict) -> bool:
    if source_type == "telegram":
        return (source_id or "").split("/")[0] in muted["telegram"]
    if source_type == "blog":
        from pipeline.urls import url_belongs
        u = url or ""
        return any(url_belongs(u, prefix) for prefix in muted["blog"])
    return False


def feed_mute_sql(conn) -> tuple[str, list]:
    """피드 쿼리용 WHERE 조각 — 뮤트 소스 제외. (조건문, 파라미터)"""
    muted = get_muted(conn)
    conds, params = [], []
    if muted["telegram"]:
        ph = ",".join("?" for _ in muted["telegram"])
        conds.append(f"(rd.source_type='telegram' AND substr(rd.source_id, 1, instr(rd.source_id,'/')-1) IN ({ph}))")
        params += list(muted["telegram"])
    from pipeline.urls import is_feedlike, norm_domain
    for u in muted["blog"]:
        if is_feedlike(u):  # RSS 직등록 소스 — 기사 url이 피드 url로 시작 안 함
            conds.append("(rd.source_type='blog' AND rd.url LIKE '%//%' || ? || '%')")
            params.append(norm_domain(u))
        else:
            conds.append("(rd.source_type='blog' AND rd.url LIKE ? || '%')")
            params.append(u)
    if not conds:
        return "1=1", []
    return f"NOT ({' OR '.join(conds)})", params
