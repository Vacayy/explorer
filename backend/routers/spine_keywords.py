"""종목별 매칭 키워드 CRUD — "이 종목은 어떤 표현으로 잡히는가"의 투명성 + 사용자 확장.

매칭 기준 3층:
  1. 정식 종목명 (결정적 substring, conf 0.6 fallback)
  2. LLM 별칭 자동 인식 ('하이닉스'→SK하이닉스, conf 0.9)
  3. 사용자 정의 키워드 (이 API — 결정적, conf 0.7. 등록 즉시 기존 문서에도 소급 링크)
"""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/keywords", tags=["spine"])


class Keyword(BaseModel):
    id: int
    keyword: str


class KeywordsResponse(BaseModel):
    stock_code: str
    official_name: str | None
    keywords: list[Keyword]
    as_of: str


class AddKeywordRequest(BaseModel):
    stock: str
    keyword: str


def _entity(conn, stock: str):
    return conn.execute(
        "SELECT id, name FROM entities WHERE type='company' AND aliases=?", (stock,)
    ).fetchone()


@router.get("", response_model=KeywordsResponse)
def list_keywords(stock: str = Query(...)):
    conn = get_connection()
    ent = _entity(conn, stock)
    if not ent:
        conn.close()
        raise HTTPException(404, "종목을 찾을 수 없습니다")
    rows = conn.execute(
        "SELECT id, keyword FROM entity_keywords WHERE entity_id=? ORDER BY created_at", (ent["id"],)
    ).fetchall()
    conn.close()
    return KeywordsResponse(
        stock_code=stock, official_name=ent["name"],
        keywords=[Keyword(id=r["id"], keyword=r["keyword"]) for r in rows],
        as_of=datetime.now(timezone.utc).isoformat(),
    )


@router.post("", status_code=201)
def add_keyword(body: AddKeywordRequest):
    kw = body.keyword.strip()
    if not kw or len(kw) > 30:
        raise HTTPException(400, "키워드는 1~30자")
    conn = get_connection()
    ent = _entity(conn, body.stock)
    if not ent:
        conn.close()
        raise HTTPException(404, "종목을 찾을 수 없습니다")
    conn.execute("INSERT OR IGNORE INTO entity_keywords (entity_id, keyword) VALUES (?, ?)",
                 (ent["id"], kw))

    # 소급 적용: 기존 문서에서 즉시 매칭 (결정적 — LLM 불필요)
    pat = rf"(?<![0-9A-Za-z가-힣]){re.escape(kw)}"
    if len(kw) <= 2:
        pat += r"(?![0-9A-Za-z가-힣])"
    rx = re.compile(pat)
    linked = 0
    for doc in conn.execute("SELECT id, title, markdown FROM raw_documents").fetchall():
        text = f"{doc['title'] or ''}\n{doc['markdown'] or ''}"
        if kw in text and rx.search(text):
            cur = conn.execute(
                "INSERT OR IGNORE INTO entity_links (doc_id, entity_id, link_type, confidence) "
                "VALUES (?, ?, 'stock', 0.7)", (doc["id"], ent["id"]))
            linked += cur.rowcount
    conn.commit()
    conn.close()
    return {"keyword": kw, "retro_linked_docs": linked}


@router.delete("/{keyword_id}", status_code=204)
def remove_keyword(keyword_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM entity_keywords WHERE id=?", (keyword_id,))
    conn.commit()
    conn.close()
