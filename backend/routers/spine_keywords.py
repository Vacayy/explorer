"""종목별 매칭 키워드 승인·삭제 — 승인 대기 별칭(ApprovalsCard)을 처리한다.

매칭 기준 3층:
  1. 정식 종목명 (결정적 substring, conf 0.6 fallback)
  2. LLM 별칭 자동 인식 ('하이닉스'→SK하이닉스, conf 0.9)
  3. 사용자 정의 키워드 (이 API — 결정적, conf 0.7. 등록 즉시 기존 문서에도 소급 링크)
"""
import re

from fastapi import APIRouter, HTTPException

from database import get_connection

router = APIRouter(prefix="/api/spine/keywords", tags=["spine"])


def _retro_link(conn, entity_id: int, kw: str) -> int:
    """키워드를 기존 문서 전체에 소급 매칭 (결정적)."""
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
                "VALUES (?, ?, 'stock', 0.7)", (doc["id"], entity_id))
            linked += cur.rowcount
    return linked


@router.post("/{keyword_id}/approve")
def approve_keyword(keyword_id: int):
    """proposed 별칭 승인 → active + 기존 문서 소급 링크."""
    conn = get_connection()
    row = conn.execute("SELECT entity_id, keyword FROM entity_keywords WHERE id=?", (keyword_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "키워드를 찾을 수 없습니다")
    conn.execute("UPDATE entity_keywords SET status='active' WHERE id=?", (keyword_id,))
    linked = _retro_link(conn, row["entity_id"], row["keyword"])
    conn.commit()
    conn.close()
    return {"keyword": row["keyword"], "retro_linked_docs": linked}


@router.delete("/{keyword_id}", status_code=204)
def remove_keyword(keyword_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM entity_keywords WHERE id=?", (keyword_id,))
    conn.commit()
    conn.close()
