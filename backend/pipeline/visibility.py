"""소스 뮤트(개인 노출 설정) — 수집은 공유 인프라, 노출은 사용자 설정.

is_active=0 = 뮤트: 내 피드·AI 답변에서 제외 (수집·다이제스트·신호 등
시스템 지능은 계속 축적 — 다시 켜면 그동안의 수집분이 그대로 보인다).
멀티유저 확장 시 이 모듈이 user_id별 뮤트 테이블로 바뀐다.
"""


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
        u = url or ""
        return any(u.startswith(prefix) for prefix in muted["blog"])
    return False


def feed_mute_sql(conn) -> tuple[str, list]:
    """피드 쿼리용 WHERE 조각 — 뮤트 소스 제외. (조건문, 파라미터)"""
    muted = get_muted(conn)
    conds, params = [], []
    if muted["telegram"]:
        ph = ",".join("?" for _ in muted["telegram"])
        conds.append(f"(rd.source_type='telegram' AND substr(rd.source_id, 1, instr(rd.source_id,'/')-1) IN ({ph}))")
        params += list(muted["telegram"])
    for u in muted["blog"]:
        conds.append("(rd.source_type='blog' AND rd.url LIKE ? || '%')")
        params.append(u)
    if not conds:
        return "1=1", []
    return f"NOT ({' OR '.join(conds)})", params
