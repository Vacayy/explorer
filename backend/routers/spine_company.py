"""기업 프로필 API — 해외/비상장 기업 (국내 종목은 /analyze 종목 상세가 담당).

인물 프로필(spine_person)과 동형: 언급 흐름 + 공출현 + 게으른 프로필 + 팔로우.
name 기반 — 향후 해외 상장 종목 데이터(주가·수급)가 붙으면 이 페이지에 확장.
프로필 저장은 source_digests(kind='company_profile', key=이름) 재사용.
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/company", tags=["spine"])
PROFILE_DOCS = 30


class CoEntity(BaseModel):
    entity_id: int
    name: str
    link_type: str
    aliases: str | None
    count: int


class CompanyDoc(BaseModel):
    id: int
    title: str
    published_at: str | None


class CompanyProfile(BaseModel):
    status: str
    digest: str | None
    insights: str | None
    created_at: str | None


class CompanyDossier(BaseModel):
    entity_id: int
    name: str
    listed: str | None          # 해외 | 비상장 | None
    category: str | None
    total_docs: int
    first_doc_at: str | None
    last_doc_at: str | None
    following: bool
    profile: CompanyProfile | None
    profile_stale: bool
    co_entities: list[CoEntity]
    recent_docs: list[CompanyDoc]


def _resolve(conn, name: str):
    # 해외/비상장(종목코드 없음) 우선 — 국내 종목은 /analyze로 가야 하므로 제외
    return conn.execute(
        "SELECT id, name, meta_json FROM entities WHERE type='company' AND name=? "
        "AND aliases IS NULL AND status IS NOT 'merged'", (name,)).fetchone()


@router.get("/{name}/dossier", response_model=CompanyDossier)
def company_dossier(name: str):
    from pipeline.source_dossier import profile_hash, get_cached
    conn = get_connection()
    ent = _resolve(conn, name)
    if not ent:
        conn.close()
        raise HTTPException(404, "기업 엔티티가 없습니다")
    meta = json.loads(ent["meta_json"]) if ent["meta_json"] else {}

    st = conn.execute("""
        SELECT count(*) n, min(rd.published_at) first, max(rd.published_at) last
        FROM entity_links el JOIN raw_documents rd ON el.doc_id = rd.id
        WHERE el.entity_id=? AND el.link_type='stock'""", (ent["id"],)).fetchone()
    docs = conn.execute("""
        SELECT rd.id, rd.title, rd.published_at FROM entity_links el
        JOIN raw_documents rd ON el.doc_id = rd.id
        WHERE el.entity_id=? AND el.link_type='stock'
        ORDER BY rd.published_at DESC LIMIT ?""", (ent["id"], PROFILE_DOCS)).fetchall()
    cached = get_cached(conn, "company_profile", name)
    hash_docs = [{"id": d["id"]} for d in docs]
    stale = bool(docs) and (not cached or cached["doc_ids_hash"] != profile_hash(hash_docs))

    co = conn.execute("""
        SELECT e2.id entity_id, e2.name, el2.link_type, e2.aliases, count(*) c
        FROM entity_links el
        JOIN entity_links el2 ON el2.doc_id = el.doc_id AND el2.entity_id != el.entity_id
        JOIN entities e2 ON el2.entity_id = e2.id AND e2.status IS NOT 'merged'
        WHERE el.entity_id=? AND el.link_type='stock'
          AND el2.link_type IN ('stock','industry','topic','person')
        GROUP BY e2.id, el2.link_type ORDER BY c DESC LIMIT 12""", (ent["id"],)).fetchall()
    following = conn.execute("SELECT 1 FROM follows WHERE entity_id=?", (ent["id"],)).fetchone() is not None
    conn.close()

    return CompanyDossier(
        entity_id=ent["id"], name=ent["name"],
        listed=meta.get("listed"), category=meta.get("category"),
        total_docs=st["n"] or 0, first_doc_at=st["first"], last_doc_at=st["last"],
        following=following,
        profile=CompanyProfile(status="cached", digest=cached["digest"],
                               insights=cached["insights"], created_at=cached["created_at"]) if cached else None,
        profile_stale=stale,
        co_entities=[CoEntity(entity_id=r["entity_id"], name=r["name"], link_type=r["link_type"],
                              aliases=r["aliases"], count=r["c"]) for r in co],
        recent_docs=[CompanyDoc(id=r["id"], title=r["title"] or "(제목 없음)",
                                published_at=r["published_at"]) for r in docs[:15]],
    )


@router.post("/{name}/profile", response_model=CompanyProfile)
def compute_company_profile(name: str):
    """게으른 기업 프로필 — 새 언급이 있을 때만 LLM (인물 프로필과 동일 규율)."""
    from pipeline.source_dossier import profile_hash, get_cached
    from pipeline.digests import _call_json, STYLE_RULES
    from pipeline.enrich import llm_engine

    conn = get_connection()
    ent = _resolve(conn, name)
    if not ent:
        conn.close()
        raise HTTPException(404, "기업 엔티티가 없습니다")
    docs = conn.execute("""
        SELECT rd.id, rd.title, rd.published_at, substr(rd.markdown, 1, 500) ex
        FROM entity_links el JOIN raw_documents rd ON el.doc_id = rd.id
        WHERE el.entity_id=? AND el.link_type='stock'
        ORDER BY rd.published_at DESC LIMIT ?""", (ent["id"], PROFILE_DOCS)).fetchall()
    cached = get_cached(conn, "company_profile", name)
    h = profile_hash([{"id": d["id"]} for d in docs])
    if not docs or (cached and cached["doc_ids_hash"] == h):
        conn.close()
        return CompanyProfile(status="cached",
                              digest=cached["digest"] if cached else None,
                              insights=cached["insights"] if cached else None,
                              created_at=cached["created_at"] if cached else None)
    if llm_engine() != "claude-code":
        conn.close()
        return CompanyProfile(status="unavailable", digest=cached["digest"] if cached else None,
                              insights=cached["insights"] if cached else None,
                              created_at=cached["created_at"] if cached else None)
    ctx = "\n\n".join(f"[{i+1}] ({(d['published_at'] or '')[:10]}) {d['title']}\n{d['ex'] or ''}"
                      for i, d in enumerate(docs))
    prior = cached["digest"] if cached else None
    prior_block = f"\n\n[지난 프로필 — 변화 판단 기준]\n{prior}" if prior else ""
    prompt = (
        f"너는 리서치센터의 기업 분석가다. 아래는 '{ent['name']}'이(가) 언급된 수집 문서 {len(docs)}건이다.\n"
        "이 기업의 프로필을 써라: ① 무슨 사업을 하고 시장에서 어떤 위치인가 ② 최근 행보·발표의 흐름 "
        "③ 이 기업의 움직임이 어떤 종목·산업·경쟁자에 파급되는지. 문서에 없는 배경지식으로 채우지 말고 "
        "수집된 내용 중심으로.\n"
        + STYLE_RULES +
        'JSON만 출력: {"digest": "마크다운 프로필", "new_insights": "지난 프로필 대비 새 행보·'
        '시각 변화 1~3문장, 없으면 null"}\n'
        f"{prior_block}\n\n[수집 문서]\n{ctx}"
    )
    try:
        data = _call_json(prompt)
    except Exception:
        conn.close()
        return CompanyProfile(status="failed", digest=prior, insights=None,
                              created_at=cached["created_at"] if cached else None)
    conn.execute("""
        INSERT INTO source_digests (kind, key, digest, insights, doc_count, doc_ids_hash, model)
        VALUES ('company_profile', ?, ?, ?, ?, ?, 'claude-code/haiku')
        ON CONFLICT(kind, key) DO UPDATE SET
            digest=excluded.digest, insights=excluded.insights, doc_count=excluded.doc_count,
            doc_ids_hash=excluded.doc_ids_hash, model=excluded.model, created_at=datetime('now')
    """, (name, data.get("digest"), data.get("new_insights") or None, len(docs), h))
    conn.commit()
    row = get_cached(conn, "company_profile", name)
    conn.close()
    return CompanyProfile(status="fresh", digest=row["digest"], insights=row["insights"],
                          created_at=row["created_at"])
