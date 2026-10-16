"""인물 도시에 API — 언급 흐름 + 연관 엔티티 + 게으른 프로필 (knowledge-system.md ③).

프로필 저장은 source_digests 테이블 재사용 (kind='person', key=이름) —
소스 도시에와 동일한 doc_ids_hash 가드·게으른 생성 규율.
"""
import threading
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/person", tags=["spine"])

PROFILE_DOCS = 30

_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _lock(name: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(name, threading.Lock())


class PersonDoc(BaseModel):
    id: int
    title: str
    published_at: str | None


class PersonEntity(BaseModel):
    entity_id: int
    name: str
    link_type: str
    aliases: str | None
    count: int


class PersonProfile(BaseModel):
    status: str
    digest: str | None
    insights: str | None
    created_at: str | None


class PersonRelation(BaseModel):
    """인과 그래프에서 이 인물이 끝점인 엣지 — 어느 내러티브에서 나왔는지와 그 주제의 현행 버전."""
    id: int
    direction: str                 # out = 인물 → 상대, in = 상대 → 인물
    rel_type: str
    other_id: int
    other_name: str
    other_type: str
    other_aliases: str | None
    mechanism: str | None
    epistemic_type: str
    created_at: str | None
    narrative_topic: str | None
    narrative_title: str | None    # 그 주제의 현행(최신) 버전 제목
    narrative_superseded: bool     # 엣지를 만든 버전이 이미 새 버전으로 대체됨


class PersonDossier(BaseModel):
    entity_id: int
    name: str
    total_docs: int
    first_doc_at: str | None
    last_doc_at: str | None
    following: bool
    profile: PersonProfile | None
    profile_stale: bool
    new_since_profile: int | None = None   # 프로필 생성 이후 수집된 언급 문서 수(프로필 없으면 None)
    co_entities: list[PersonEntity]
    recent_docs: list[PersonDoc]
    relations: list[PersonRelation] = []


class PersonRow(BaseModel):
    entity_id: int
    name: str
    doc_count: int
    last_doc_at: str | None
    last_doc_title: str | None
    last_doc_id: int | None
    following: bool
    top_stocks: list[str]   # 함께 언급되는 종목 상위 (파급 경로 미리보기)
    mentions_7d: int = 0
    mentions_prev_7d: int = 0
    delta_7d: int = 0       # 최근 7일 − 그 전 7일


class PeopleDirectory(BaseModel):
    items: list[PersonRow]
    total: int              # 기간 안에 언급된 인물 수(롱테일 포함)
    hidden_tail: int        # min_mentions 미만이라 뺀 인물 수(팔로우 인물은 늘 보인다)
    as_of: str | None       # 인물 언급 문서 중 가장 최근 게시 시각


_WEEK = "datetime('now', '-7 days')"
_PREV_WEEK = "datetime('now', '-14 days')"


def aggregate_people(conn, *, days: int = 0, followed_only: bool = False, stock_days: int = 0) -> list[dict]:
    """인물별 언급 집계를 쿼리 3번으로 — 인물마다 상관 서브쿼리 2개(N+1, 약 6,800쿼리·20초)를 대체.

    ① 언급 수·최근 시각·7일/직전 7일 ② 최근 문서 1건(창 함수) ③ 함께 언급된 종목 상위 3(창 함수).
    days>0이면 ①을 그 기간으로 자른다. stock_days>0이면 ③을 그 기간 문서로 자른다.
    """
    # 기간 창은 WHERE가 아니라 집계 안에서 — 7일 Δ가 창 밖(직전 7일)을 봐야 한다
    in_win = f"datetime(rd.published_at) >= datetime('now', '-{int(days)} days')" if days else "1"
    only = "AND el.entity_id IN (SELECT entity_id FROM follows)" if followed_only else ""
    base = conn.execute(f"""
        SELECT el.entity_id id, e.name, SUM({in_win}) n, MAX(CASE WHEN {in_win} THEN rd.published_at END) last_at,
               SUM(datetime(rd.published_at) >= {_WEEK}) n7,
               SUM(datetime(rd.published_at) >= {_PREV_WEEK} AND datetime(rd.published_at) < {_WEEK}) p7,
               EXISTS(SELECT 1 FROM follows f WHERE f.entity_id = el.entity_id) following
        FROM entity_links el
        JOIN entities e ON e.id = el.entity_id AND e.type = 'person'
        JOIN raw_documents rd ON rd.id = el.doc_id
        WHERE el.link_type = 'person' {only}
        GROUP BY el.entity_id HAVING SUM({in_win}) > 0 OR {1 if followed_only else 0}""").fetchall()
    last = {r["pid"]: r for r in conn.execute(f"""
        SELECT pid, doc_id, title FROM (
            SELECT el.entity_id pid, rd.id doc_id, rd.title,
                   ROW_NUMBER() OVER (PARTITION BY el.entity_id ORDER BY rd.published_at DESC) rn
            FROM entity_links el JOIN raw_documents rd ON rd.id = el.doc_id
            WHERE el.link_type = 'person' {only}) WHERE rn = 1""")}
    stock_since = (f"AND el1.doc_id IN (SELECT id FROM raw_documents WHERE datetime(published_at) >= "
                   f"datetime('now', '-{int(stock_days)} days'))") if stock_days else ""
    stocks: dict[int, list[str]] = {}
    for r in conn.execute(f"""
        SELECT pid, name FROM (
            SELECT el1.entity_id pid, e2.name,
                   ROW_NUMBER() OVER (PARTITION BY el1.entity_id ORDER BY COUNT(*) DESC, e2.id) rn
            FROM entity_links el1
            JOIN entity_links el2 ON el2.doc_id = el1.doc_id AND el2.link_type = 'stock'
            JOIN entities e2 ON e2.id = el2.entity_id AND e2.type = 'company'
            WHERE el1.link_type = 'person' {only.replace('el.', 'el1.')} {stock_since}
            GROUP BY el1.entity_id, e2.id) WHERE rn <= 3 ORDER BY pid, rn"""):
        stocks.setdefault(r["pid"], []).append(r["name"])
    out = []
    for r in base:
        lr = last.get(r["id"])
        n7, p7 = r["n7"] or 0, r["p7"] or 0
        out.append({"entity_id": r["id"], "name": r["name"], "doc_count": r["n"], "last_doc_at": r["last_at"],
                    "last_doc_title": lr["title"] if lr else None, "last_doc_id": lr["doc_id"] if lr else None,
                    "following": bool(r["following"]), "top_stocks": stocks.get(r["id"], []),
                    "mentions_7d": n7, "mentions_prev_7d": p7, "delta_7d": n7 - p7})
    return out


_SORTS = {
    "surge": lambda r: (-r["delta_7d"], -r["mentions_7d"], -r["doc_count"]),
    "total": lambda r: (-r["doc_count"], -(r["mentions_7d"])),
    "recent": lambda r: (r["last_doc_at"] is None, [-ord(c) for c in (r["last_doc_at"] or "")]),
}


@router.get("", response_model=PeopleDirectory)
def list_people(days: int = Query(0, ge=0, le=365),
                sort: Literal["surge", "total", "recent"] = "surge",
                min_mentions: int = Query(2, ge=1, description="이 수 미만 언급 인물은 숨김(팔로우 인물 제외)")):
    """인물 디렉토리 — 기본 '7일 급상승'(최근 7일 − 직전 7일) 순, 언급 1건짜리 롱테일은 숨긴다.

    days>0이면 해당 기간 내 언급된 인물만, 언급 수도 그 기간 기준.
    """
    conn = get_connection()
    rows = aggregate_people(conn, days=days)
    conn.close()
    shown = [r for r in rows if r["doc_count"] >= min_mentions or r["following"]]
    shown.sort(key=_SORTS[sort])
    as_of = max((r["last_doc_at"] for r in rows if r["last_doc_at"]), default=None)
    return PeopleDirectory(items=[PersonRow(**r) for r in shown], total=len(rows),
                           hidden_tail=len(rows) - len(shown), as_of=as_of)


class FollowedWeek(BaseModel):
    items: list[PersonRow]  # top_stocks = 최근 7일 문서에서 함께 뜬 종목
    as_of: str | None


@router.get("/followed", response_model=FollowedWeek)
def followed_week():
    """팔로우 인물의 이번 주 — 7일 언급과 직전 7일 대비 Δ, 최신 문서 1건(홈 위젯, 읽기 전용)."""
    conn = get_connection()
    rows = aggregate_people(conn, followed_only=True, stock_days=7)
    conn.close()
    rows.sort(key=_SORTS["surge"])
    as_of = max((r["last_doc_at"] for r in rows if r["last_doc_at"]), default=None)
    return FollowedWeek(items=[PersonRow(**r) for r in rows], as_of=as_of)


def _resolve(conn, name: str):
    return conn.execute(
        "SELECT id, name FROM entities WHERE type='person' AND name=?", (name,)).fetchone()


def _recent_docs(conn, entity_id: int, limit: int):
    return conn.execute("""
        SELECT rd.id, rd.title, rd.published_at, substr(rd.markdown, 1, 500) ex
        FROM entity_links el JOIN raw_documents rd ON el.doc_id = rd.id
        WHERE el.entity_id=? AND el.link_type='person'
        ORDER BY rd.published_at DESC LIMIT ?""", (entity_id, limit)).fetchall()


@router.get("/{name}/dossier", response_model=PersonDossier)
def person_dossier(name: str):
    """LLM 호출 없음 — 캐시된 프로필 + stale 플래그."""
    from pipeline.source_dossier import profile_hash, get_cached
    conn = get_connection()
    ent = _resolve(conn, name)
    if not ent:
        conn.close()
        raise HTTPException(404, "인물 엔티티가 없습니다")

    st = conn.execute("""
        SELECT count(*) n, min(rd.published_at) first, max(rd.published_at) last
        FROM entity_links el JOIN raw_documents rd ON el.doc_id = rd.id
        WHERE el.entity_id=? AND el.link_type='person'""", (ent["id"],)).fetchone()

    docs = _recent_docs(conn, ent["id"], PROFILE_DOCS)
    cached = get_cached(conn, "person", name)
    stale = bool(docs) and (not cached or cached["doc_ids_hash"] != profile_hash(docs))

    co = conn.execute("""
        SELECT e2.id entity_id, e2.name, el2.link_type, e2.aliases, count(*) c
        FROM entity_links el
        JOIN entity_links el2 ON el2.doc_id = el.doc_id AND el2.entity_id != el.entity_id
        JOIN entities e2 ON el2.entity_id = e2.id
        WHERE el.entity_id=? AND el.link_type='person'
          AND el2.link_type IN ('stock','industry','topic','person')
        GROUP BY e2.id, el2.link_type ORDER BY c DESC LIMIT 12""", (ent["id"],)).fetchall()

    following = conn.execute(
        "SELECT 1 FROM follows WHERE entity_id=?", (ent["id"],)).fetchone() is not None
    new_since = None
    if cached:
        new_since = conn.execute("""
            SELECT count(*) FROM entity_links el JOIN raw_documents rd ON rd.id = el.doc_id
            WHERE el.entity_id=? AND el.link_type='person' AND rd.fetched_at > ?""",
                                 (ent["id"], cached["created_at"])).fetchone()[0]
    relations = _relations(conn, ent["id"])
    conn.close()

    return PersonDossier(
        entity_id=ent["id"], name=ent["name"],
        total_docs=st["n"] or 0, first_doc_at=st["first"], last_doc_at=st["last"],
        following=following,
        profile=PersonProfile(status="cached", digest=cached["digest"],
                              insights=cached["insights"], created_at=cached["created_at"]) if cached else None,
        profile_stale=stale,
        new_since_profile=new_since,
        relations=relations,
        co_entities=[PersonEntity(entity_id=r["entity_id"], name=r["name"],
                                  link_type=r["link_type"], aliases=r["aliases"], count=r["c"]) for r in co],
        recent_docs=[PersonDoc(id=r["id"], title=r["title"] or "(제목 없음)",
                               published_at=r["published_at"]) for r in docs[:15]],
    )


def _relations(conn, entity_id: int, limit: int = 20) -> list[PersonRelation]:
    """인물이 src·dst인 인과 엣지 + 출처 내러티브 주제의 현행 버전(읽기 전용)."""
    rows = conn.execute("""
        SELECT r.id, CASE WHEN r.src_id = :e THEN 'out' ELSE 'in' END direction, r.rel_type,
               o.id other_id, o.name other_name, o.type other_type, o.aliases other_aliases,
               r.mechanism, r.epistemic_type, r.created_at,
               n.topic, n.superseded_at,
               (SELECT COALESCE(NULLIF(l.title, ''), l.topic) FROM narratives l
                 WHERE l.topic = n.topic ORDER BY l.version DESC LIMIT 1) latest_title
        FROM entity_relations r
        JOIN entities o ON o.id = CASE WHEN r.src_id = :e THEN r.dst_id ELSE r.src_id END
        LEFT JOIN narratives n ON n.id = r.narrative_id
        WHERE r.src_id = :e OR r.dst_id = :e
        ORDER BY r.created_at DESC, r.id DESC LIMIT :lim""", {"e": entity_id, "lim": limit}).fetchall()
    return [PersonRelation(id=r["id"], direction=r["direction"], rel_type=r["rel_type"], other_id=r["other_id"],
                           other_name=r["other_name"], other_type=r["other_type"], other_aliases=r["other_aliases"],
                           mechanism=r["mechanism"], epistemic_type=r["epistemic_type"] or "fact",
                           created_at=r["created_at"], narrative_topic=r["topic"], narrative_title=r["latest_title"],
                           narrative_superseded=bool(r["superseded_at"])) for r in rows]


@router.post("/{name}/profile", response_model=PersonProfile)
def compute_person_profile(name: str):
    """게으른 프로필 — 새 언급이 있을 때만 haiku (소스 도시에와 동일 규율)."""
    from pipeline.source_dossier import profile_hash, get_cached
    from pipeline.digests import STYLE_RULES, _call_json
    from pipeline.enrich import llm_engine

    with _lock(name):
        conn = get_connection()
        ent = _resolve(conn, name)
        if not ent:
            conn.close()
            raise HTTPException(404, "인물 엔티티가 없습니다")
        docs = _recent_docs(conn, ent["id"], PROFILE_DOCS)
        if not docs:
            conn.close()
            return PersonProfile(status="empty", digest=None, insights=None, created_at=None)
        h = profile_hash(docs)
        cached = get_cached(conn, "person", name)
        if cached and cached["doc_ids_hash"] == h:
            conn.close()
            return PersonProfile(status="cached", digest=cached["digest"],
                                 insights=cached["insights"], created_at=cached["created_at"])
        if llm_engine() != "claude-code":
            conn.close()
            return PersonProfile(status="unavailable",
                                 digest=cached["digest"] if cached else None,
                                 insights=cached["insights"] if cached else None,
                                 created_at=cached["created_at"] if cached else None)

        prior = cached["digest"] if cached else None
        ctx = "\n\n".join(f"[{(d['published_at'] or '')[:10]}] {d['title']}\n{d['ex'] or ''}" for d in docs)
        prior_block = f"\n\n[지난 프로필 — 변화 판단 기준]\n{prior}" if prior else ""
        prompt = (
            f"너는 리서치센터의 인물 분석가다. 아래는 '{ent['name']}'이(가) 언급되거나 직접 발언한 "
            f"수집 문서 {len(docs)}건이다.\n"
            "이 인물의 프로필을 써라: ① 시장에서 이 인물이 갖는 위치·영향력 ② 최근 행보와 발언의 "
            "흐름 ③ 이 인물의 움직임이 어떤 종목·산업에 파급되는지. 문서에 없는 배경지식으로 "
            "채우지 말고 수집된 내용 중심으로.\n"
            + STYLE_RULES +
            'JSON만 출력: {"digest": "마크다운 프로필", "new_insights": "지난 프로필 대비 새 행보·'
            '시각 변화 1~3문장, 없으면 null"}\n'
            f"{prior_block}\n\n[수집 문서]\n{ctx}"
        )
        try:
            data = _call_json(prompt)  # LLM — 쓰기 트랜잭션 밖
        except Exception:
            conn.close()
            return PersonProfile(status="failed",
                                 digest=prior, insights=cached["insights"] if cached else None,
                                 created_at=cached["created_at"] if cached else None)

        conn.execute("""
            INSERT INTO source_digests (kind, key, digest, insights, doc_count, doc_ids_hash, model)
            VALUES ('person', ?, ?, ?, ?, ?, 'claude-code/haiku')
            ON CONFLICT(kind, key) DO UPDATE SET
                digest=excluded.digest, insights=excluded.insights, doc_count=excluded.doc_count,
                doc_ids_hash=excluded.doc_ids_hash, model=excluded.model, created_at=datetime('now')
        """, (name, data.get("digest"), data.get("new_insights") or None, len(docs), h))
        conn.commit()
        row = get_cached(conn, "person", name)
        conn.close()
        return PersonProfile(status="fresh", digest=row["digest"], insights=row["insights"],
                             created_at=row["created_at"])
