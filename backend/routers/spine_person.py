"""인물 도시에 API — 언급 흐름 + 연관 엔티티 + 게으른 프로필 (knowledge-system.md ③).

프로필 저장은 source_digests 테이블 재사용 (kind='person', key=이름) —
소스 도시에와 동일한 doc_ids_hash 가드·게으른 생성 규율.
"""
import threading

from fastapi import APIRouter, HTTPException
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


class PersonDossier(BaseModel):
    entity_id: int
    name: str
    total_docs: int
    first_doc_at: str | None
    last_doc_at: str | None
    following: bool
    profile: PersonProfile | None
    profile_stale: bool
    co_entities: list[PersonEntity]
    recent_docs: list[PersonDoc]


class PersonRow(BaseModel):
    entity_id: int
    name: str
    doc_count: int
    last_doc_at: str | None
    last_doc_title: str | None
    last_doc_id: int | None
    following: bool
    top_stocks: list[str]   # 함께 언급되는 종목 상위 (파급 경로 미리보기)


@router.get("", response_model=list[PersonRow])
def list_people(days: int = 0):
    """인물 디렉토리 — 수집된 전체 인물 + 최근 발언 (탐색의 발견 표면).

    days>0이면 해당 기간 내 언급된 인물만 (기본: 전체, 언급 수 순).
    """
    conn = get_connection()
    since = f"AND rd.published_at >= datetime('now', '-{int(days)} days')" if days else ""
    rows = conn.execute(f"""
        SELECT e.id, e.name, COUNT(DISTINCT el.doc_id) n, MAX(rd.published_at) last_at,
               (SELECT 1 FROM follows f WHERE f.entity_id = e.id) following
        FROM entities e
        JOIN entity_links el ON el.entity_id = e.id AND el.link_type='person'
        JOIN raw_documents rd ON rd.id = el.doc_id
        WHERE e.type='person' {since}
        GROUP BY e.id ORDER BY n DESC, last_at DESC""").fetchall()
    out = []
    for r in rows:
        last = conn.execute("""
            SELECT rd.id, rd.title FROM entity_links el JOIN raw_documents rd ON rd.id = el.doc_id
            WHERE el.entity_id=? AND el.link_type='person'
            ORDER BY rd.published_at DESC LIMIT 1""", (r["id"],)).fetchone()
        stocks = [s["name"] for s in conn.execute("""
            SELECT e2.name, COUNT(*) c FROM entity_links el1
            JOIN entity_links el2 ON el2.doc_id = el1.doc_id AND el2.link_type='stock'
            JOIN entities e2 ON e2.id = el2.entity_id AND e2.type='company'
            WHERE el1.entity_id=? AND el1.link_type='person'
            GROUP BY e2.id ORDER BY c DESC LIMIT 3""", (r["id"],))]
        out.append(PersonRow(
            entity_id=r["id"], name=r["name"], doc_count=r["n"], last_doc_at=r["last_at"],
            last_doc_title=last["title"] if last else None,
            last_doc_id=last["id"] if last else None,
            following=bool(r["following"]), top_stocks=stocks))
    conn.close()
    return out


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
    conn.close()

    return PersonDossier(
        entity_id=ent["id"], name=ent["name"],
        total_docs=st["n"] or 0, first_doc_at=st["first"], last_doc_at=st["last"],
        following=following,
        profile=PersonProfile(status="cached", digest=cached["digest"],
                              insights=cached["insights"], created_at=cached["created_at"]) if cached else None,
        profile_stale=stale,
        co_entities=[PersonEntity(entity_id=r["entity_id"], name=r["name"],
                                  link_type=r["link_type"], aliases=r["aliases"], count=r["c"]) for r in co],
        recent_docs=[PersonDoc(id=r["id"], title=r["title"] or "(제목 없음)",
                               published_at=r["published_at"]) for r in docs[:15]],
    )


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
